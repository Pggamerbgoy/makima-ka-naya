"""
Makima v2 — OpenAI-Compatible Provider Adapter.
Drives Groq (Free tier Llama 3.3 70B), OpenRouter (Free models), and local Ollama (100% offline).
Zero-Cost Guarantee: Zero mandatory paid keys. Operates natively with free tiers and local daemon.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from openai import AsyncOpenAI

from makima.config import BackendConfig
from makima.provider.adapters.base import (
    BaseProvider,
    Message,
    ProviderResponse,
    StreamChunk,
    ToolCall,
)
from makima.provider.cache import CacheStrategy, get_cache_manager
from makima.provider.circuit_breaker import CircuitBreaker


class OpenAICompatibleProvider(BaseProvider):
    """
    Adapter for standard OpenAI Chat Completions API format.
    Fully compatible with Groq, OpenRouter, Cerebras, and Ollama localhost.
    Integrated with Unified Prompt & KV Cache Manager.
    """

    def __init__(
        self,
        config: BackendConfig,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        super().__init__(config=config, circuit_breaker=circuit_breaker)
        self._client: Optional[AsyncOpenAI] = None
        self._cached_tools_key: Optional[str] = None
        self._cached_tools_payload: Optional[List[Dict[str, Any]]] = None
        self.cache_manager = get_cache_manager()
        self.cache_strategy = self.cache_manager.get_strategy(
            adapter=config.adapter,
            base_url=config.base_url,
            model=config.model,
        )

    def _supports_explicit_cache_control(self) -> bool:
        """
        Checks if the target endpoint supports Anthropic/OpenRouter explicit
        `cache_control: {"type": "ephemeral"}` content blocks.
        """
        return self.cache_strategy == CacheStrategy.EXPLICIT_CACHE_CONTROL

    def _get_client(self) -> AsyncOpenAI:
        """Initializes AsyncOpenAI client with target base_url and API key."""
        if self._client is None:
            # Ollama does not require real API key; default to dummy string
            api_key = self.config.api_key or ("ollama" if self.config.adapter == "ollama" else None)
            if not api_key:
                raise ValueError(
                    f"Missing API key for provider '{self.name}'. "
                    f"Please configure '{self.config.api_key_env}' in environment or .env."
                )

            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=self.config.base_url,
                timeout=60.0,
            )
        return self._client

    def _format_messages(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Formats canonical messages into OpenAI chat payload format with prompt-cache alignment."""
        return self.cache_manager.format_messages(
            messages=messages,
            system_prompt=system_prompt,
            strategy=self.cache_strategy,
        )

    def _format_tools(self, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """Ensures tools comply with standard OpenAI function schema structure with canonical sorting & caching."""
        return self.cache_manager.format_tools(
            tools=tools,
            strategy=self.cache_strategy,
        )

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> ProviderResponse:
        await self._before_call()
        start_time = time.monotonic()

        try:
            client = self._get_client()
            formatted_messages = self._format_messages(messages, system_prompt=system_prompt)
            formatted_tools = self._format_tools(tools)

            call_kwargs: Dict[str, Any] = {
                "model": self.config.model,
                "messages": formatted_messages,
                "temperature": temperature,
            }
            if max_tokens:
                call_kwargs["max_tokens"] = max_tokens
            if formatted_tools:
                call_kwargs["tools"] = formatted_tools
            if kwargs.get("tool_choice"):
                call_kwargs["tool_choice"] = kwargs["tool_choice"]
            elif kwargs.get("force_synthesis"):
                call_kwargs["tool_choice"] = "none"

            enable_thinking = kwargs.pop("enable_thinking", None)
            if enable_thinking is not None:
                base_lower = (self.config.base_url or "").lower()
                if "dashscope" in base_lower:
                    call_kwargs["extra_body"] = {
                        "enable_thinking": bool(enable_thinking)
                    }
                elif "groq" in base_lower or "openrouter" in base_lower:
                    if enable_thinking:
                        call_kwargs["extra_body"] = {"reasoning_effort": "medium"}

            response = await client.chat.completions.create(**call_kwargs)
            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            await self._on_success()

            choice = response.choices[0]
            content = choice.message.content
            if not content:
                reasoning = getattr(choice.message, "reasoning_content", None)
                if not reasoning and hasattr(choice.message, "model_extra") and isinstance(choice.message.model_extra, dict):
                    reasoning = choice.message.model_extra.get("reasoning_content")
                if reasoning and isinstance(reasoning, str) and reasoning.strip():
                    content = reasoning.strip()
            tool_calls: List[ToolCall] = []

            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    args: Dict[str, Any] = {}
                    if tc.function.arguments:
                        try:
                            args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            args = {"raw_arguments": tc.function.arguments}
                    tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=args,
                        )
                    )

            usage = None
            if response.usage:
                cached_tokens = self.cache_manager.extract_cached_tokens(response)
                p_tok = getattr(response.usage, "prompt_tokens", 0) or 0
                c_tok = getattr(response.usage, "completion_tokens", 0) or 0
                t_tok = getattr(response.usage, "total_tokens", 0) or 0
                usage = {
                    "prompt_tokens": p_tok,
                    "completion_tokens": c_tok,
                    "total_tokens": t_tok,
                    "cached_tokens": cached_tokens,
                }
                self.cache_manager.record_usage(
                    model=self.config.model,
                    prompt_tokens=p_tok,
                    cached_tokens=cached_tokens,
                )

            return ProviderResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=choice.finish_reason or "stop",
                usage=usage,
                model=self.config.model,
                latency_ms=elapsed_ms,
                raw=response,
            )

        except Exception as e:
            await self._on_failure(e)
            raise

    async def stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        await self._before_call()
        try:
            client = self._get_client()
            formatted_messages = self._format_messages(messages, system_prompt=system_prompt)
            formatted_tools = self._format_tools(tools)

            call_kwargs: Dict[str, Any] = {
                "model": self.config.model,
                "messages": formatted_messages,
                "temperature": temperature,
                "stream": True,
            }
            if max_tokens:
                call_kwargs["max_tokens"] = max_tokens
            if formatted_tools:
                call_kwargs["tools"] = formatted_tools
            if kwargs.get("tool_choice"):
                call_kwargs["tool_choice"] = kwargs["tool_choice"]
            elif kwargs.get("force_synthesis"):
                call_kwargs["tool_choice"] = "none"

            base_l = (self.config.base_url or "").lower()
            if any(k in base_l for k in ("openai.com", "openrouter.ai", "groq.com", "deepseek.com")):
                call_kwargs["stream_options"] = {"include_usage": True}

            stream_resp = await client.chat.completions.create(**call_kwargs)
            # Function call IDs, names, and JSON arguments arrive across multiple
            # delta chunks. Accumulate them instead of silently dropping tool calls.
            pending_tool_calls: Dict[int, Dict[str, str]] = {}
            last_finish_reason: Optional[str] = None

            async for chunk in stream_resp:
                if hasattr(chunk, "usage") and chunk.usage:
                    c_tok = self.cache_manager.extract_cached_tokens(chunk.usage)
                    p_tok = getattr(chunk.usage, "prompt_tokens", 0) or 0
                    self.cache_manager.record_usage(
                        model=self.config.model,
                        prompt_tokens=p_tok,
                        cached_tokens=c_tok,
                    )

                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                delta_text = getattr(delta, "content", None) or ""
                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason:
                    last_finish_reason = str(finish_reason)

                for tool_delta in (getattr(delta, "tool_calls", None) or []):
                    raw_index = getattr(tool_delta, "index", None)
                    try:
                        tool_index = int(raw_index)
                    except (TypeError, ValueError):
                        tool_index = len(pending_tool_calls)
                    entry = pending_tool_calls.setdefault(
                        tool_index,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    call_id = getattr(tool_delta, "id", None)
                    if call_id:
                        entry["id"] = str(call_id)
                    function_delta = getattr(tool_delta, "function", None)
                    fn_name = getattr(function_delta, "name", None)
                    if fn_name:
                        entry["name"] += str(fn_name)
                    arguments_fragment = getattr(function_delta, "arguments", None)
                    if arguments_fragment:
                        entry["arguments"] += str(arguments_fragment)

                yield StreamChunk(
                    delta=delta_text,
                    finish_reason=finish_reason,
                )

            if pending_tool_calls:
                completed_calls: List[ToolCall] = []
                for tool_index in sorted(pending_tool_calls):
                    parts = pending_tool_calls[tool_index]
                    raw_arguments = parts["arguments"] or "{}"
                    try:
                        parsed_arguments = json.loads(raw_arguments)
                        if not isinstance(parsed_arguments, dict):
                            parsed_arguments = {"raw_arguments": raw_arguments}
                    except json.JSONDecodeError:
                        parsed_arguments = {"raw_arguments": raw_arguments}
                    completed_calls.append(
                        ToolCall(
                            id=parts["id"] or f"stream_call_{tool_index}",
                            name=parts["name"],
                            arguments=parsed_arguments,
                        )
                    )
                yield StreamChunk(
                    delta="",
                    tool_calls=completed_calls,
                    finish_reason="tool_calls",
                )

            await self._on_success()

        except Exception as e:
            await self._on_failure(e)
            raise
