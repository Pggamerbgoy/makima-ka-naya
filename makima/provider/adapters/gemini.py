"""
Makima v2 — Google GenAI SDK Adapter.
Architectural Pattern: Official google-genai SDK with streaming, function calling, and free-tier optimization.
Zero-Hardcoding Guarantee: Dynamically reads GEMINI_API_KEY and backend config.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from google import genai
from google.genai import types

from makima.config import BackendConfig
from makima.provider.adapters.base import (
    BaseProvider,
    Message,
    ProviderResponse,
    StreamChunk,
    ToolCall,
)
from makima.provider.cache import (
    CacheStrategy,
    canonicalize_tool_schemas,
    get_cache_manager,
)
from makima.provider.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class GeminiProvider(BaseProvider):
    """
    Adapter for Google Gemini models (e.g. gemini-2.5-flash) using official google-genai SDK.
    Optimized for high-speed free tier quotas on Google AI Studio.
    Integrated with Unified Prompt & Context Cache Coordinator.
    """

    def __init__(
        self,
        config: BackendConfig,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        super().__init__(config=config, circuit_breaker=circuit_breaker)
        self._client: Optional[genai.Client] = None
        self._cached_tools_key: Optional[str] = None
        self._cached_tools_payload: Optional[List[types.Tool]] = None
        self._active_cache_key: Optional[str] = None
        self._active_cache_name: Optional[str] = None
        self._active_cache_expiry: float = 0.0
        self.cache_manager = get_cache_manager()
        self.cache_strategy = CacheStrategy.EXPLICIT_GENAI

    def _get_client(self) -> genai.Client:
        """Lazy initialization of genai.Client with active API key."""
        api_key = self.config.api_key
        if not api_key:
            raise ValueError(
                f"Missing API key for Gemini backend '{self.name}'. "
                f"Ensure environment variable '{self.config.api_key_env or 'GEMINI_API_KEY'}' is set."
            )
        if self._client is None:
            self._client = genai.Client(api_key=api_key)
        return self._client

    def _convert_tools(self, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[types.Tool]]:
        """Converts standard JSON schema tool definitions into Gemini Tool format with canonical sorting & caching."""
        canonical_tools = canonicalize_tool_schemas(tools)
        if not canonical_tools:
            return None

        names_key = ",".join(
            str(t.get("function", t).get("name", ""))
            for t in canonical_tools
        )
        if names_key and self._cached_tools_key == names_key and self._cached_tools_payload is not None:
            return self._cached_tools_payload

        declarations = []
        for t in canonical_tools:
            fn = t.get("function", t)
            name = fn.get("name")
            description = fn.get("description", "")
            parameters = fn.get("parameters", {})
            if name:
                declarations.append(
                    types.FunctionDeclaration(
                        name=name,
                        description=description,
                        parameters=parameters,
                    )
                )

        if not declarations:
            return None
        result = [types.Tool(function_declarations=declarations)]
        if names_key:
            self._cached_tools_key = names_key
            self._cached_tools_payload = result
        return result

    def _convert_messages(self, messages: List[Message]) -> List[types.Content]:
        """
        Translates canonical Message list into Gemini Content objects.
        Guarantees:
        1. Strict role alternation ('user' -> 'model' -> 'user' -> 'model').
        2. Merges contiguous tool execution responses (and parallel tool outputs)
           into a single user Content turn containing matching FunctionResponse parts.
        3. Never pollutes tool response turns with duplicate raw text parts.
        4. Parses JSON tool outputs into native dicts so Gemini sees structured data.
        5. Ensures the conversation sequence starts with a 'user' turn.
        """
        contents: List[types.Content] = []

        for msg in messages:
            if msg.role == "assistant":
                role = "model"
            else:
                # Both 'user' and 'tool' (and 'system' if present in messages) map to Gemini 'user'
                role = "user"

            parts: List[types.Part] = []

            if msg.role == "tool":
                # Tool execution response: strictly produce FunctionResponse part
                resp_payload: Dict[str, Any]
                if isinstance(msg.content, str):
                    try:
                        parsed = json.loads(msg.content)
                        if isinstance(parsed, dict):
                            resp_payload = parsed
                        else:
                            resp_payload = {"result": parsed}
                    except Exception:
                        resp_payload = {"result": msg.content or ""}
                elif isinstance(msg.content, dict):
                    resp_payload = msg.content
                else:
                    resp_payload = {"result": str(msg.content or "")}

                parts.append(
                    types.Part.from_function_response(
                        name=msg.name or "tool_result",
                        response=resp_payload,
                    )
                )
            else:
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))

                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        parts.append(
                            types.Part.from_function_call(
                                name=tc.name,
                                args=tc.arguments or {},
                            )
                        )

            if not parts:
                continue

            # Maintain strict turn alternation by merging contiguous parts of the same role
            if contents and contents[-1].role == role:
                contents[-1].parts.extend(parts)
            else:
                contents.append(types.Content(role=role, parts=parts))

        # Gemini requires that the first turn is always 'user'
        if contents and contents[0].role == "model":
            contents.insert(
                0,
                types.Content(role="user", parts=[types.Part.from_text(text="Hello")]),
            )

        return contents

    async def _get_or_create_context_cache(
        self,
        system_prompt: Optional[str],
        gemini_tools: Optional[List[types.Tool]],
    ) -> Optional[str]:
        """
        Retrieves or creates an explicit Google Gemini Context Cache (KV Cache)
        containing the heavy system prompt and all registered tool declarations.
        Returns the cached_content identifier (e.g. 'cachedContents/abc123xyz')
        or None if caching is not applicable, below minimum token floor, or fails.
        """
        if not gemini_tools and not system_prompt:
            return None

        tools_repr = str([t.function_declarations for t in gemini_tools]) if gemini_tools else ""
        cache_seed = f"{self.config.model}:{system_prompt or ''}:{tools_repr}"
        cache_key = hashlib.sha256(cache_seed.encode("utf-8")).hexdigest()

        now = time.monotonic()
        if self._active_cache_key == cache_key and self._active_cache_name:
            if now < self._active_cache_expiry:
                return self._active_cache_name

        try:
            client = self._get_client()
            cache_config = types.CreateCachedContentConfig(
                display_name=f"makima_kv_{cache_key[:8]}",
                system_instruction=system_prompt,
                tools=gemini_tools,
                ttl="3600s",
            )
            cache_obj = await client.aio.caches.create(
                model=self.config.model,
                config=cache_config,
            )
            cache_name = getattr(cache_obj, "name", None)
            if cache_name:
                self._active_cache_key = cache_key
                self._active_cache_name = cache_name
                self._active_cache_expiry = now + 3500.0
                logger.info("Created Gemini KV Context Cache '%s' for model %s (saving ~11k+ tokens/turn)", cache_name, self.config.model)
                return cache_name
        except Exception as exc:
            logger.debug("Gemini KV Context Caching skipped/fallback: %s", exc)

        return None

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
            contents = self._convert_messages(messages)
            gemini_tools = self._convert_tools(tools)

            # Auto-synthesize minimal declarations for historical function calls if tools was omitted,
            # preventing Google GenAI 400 "Tool call not found in tools" during synthesis passes.
            historical_fn_names: Set[str] = set()
            for c in contents:
                if c.parts:
                    for p in c.parts:
                        if p.function_call and p.function_call.name:
                            historical_fn_names.add(p.function_call.name)
                        elif p.function_response and p.function_response.name:
                            historical_fn_names.add(p.function_response.name)

            if historical_fn_names and not gemini_tools:
                synth_decls = [
                    types.FunctionDeclaration(
                        name=fn_name,
                        description=f"Historical tool declaration for {fn_name}",
                        parameters={"type": "object", "properties": {}},
                    )
                    for fn_name in sorted(historical_fn_names)
                ]
                gemini_tools = [types.Tool(function_declarations=synth_decls)]

            tool_config: Optional[types.ToolConfig] = None
            if kwargs.get("tool_choice") == "none" or kwargs.get("force_synthesis") or (tools is None and historical_fn_names):
                tool_config = types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="NONE"
                    )
                )

            cached_content_name = await self._get_or_create_context_cache(
                system_prompt=system_prompt,
                gemini_tools=gemini_tools,
            )

            enable_thinking = kwargs.get("enable_thinking")
            thinking_config: Optional[types.ThinkingConfig] = None
            if enable_thinking is not None:
                # thinking_budget=-1 enables dynamic CoT reasoning; 0 explicitly turns it off
                thinking_config = types.ThinkingConfig(thinking_budget=-1 if enable_thinking else 0)

            if cached_content_name:
                config = types.GenerateContentConfig(
                    cached_content=cached_content_name,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    tool_config=tool_config,
                    thinking_config=thinking_config,
                )
            else:
                config = types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    tools=gemini_tools,
                    tool_config=tool_config,
                    thinking_config=thinking_config,
                )

            try:
                response = await client.aio.models.generate_content(
                    model=self.config.model,
                    contents=contents,
                    config=config,
                )
            except Exception as gen_err:
                err_str = str(gen_err).lower()
                if cached_content_name and any(k in err_str for k in ("not found", "404", "cachedcontent", "cached_content")):
                    logger.warning("Gemini context cache %s expired or evicted; retrying with direct prompt: %s", cached_content_name, gen_err)
                    self._active_cache_name = None
                    self._active_cache_key = None
                    config = types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                        tools=gemini_tools,
                        tool_config=tool_config,
                        thinking_config=thinking_config,
                    )
                    response = await client.aio.models.generate_content(
                        model=self.config.model,
                        contents=contents,
                        config=config,
                    )
                elif thinking_config is not None and "thinking" in err_str:
                    logger.warning("Gemini thinking_config not supported by %s; retrying without thinking: %s", self.config.model, gen_err)
                    config.thinking_config = None
                    response = await client.aio.models.generate_content(
                        model=self.config.model,
                        contents=contents,
                        config=config,
                    )
                else:
                    raise gen_err

            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            await self._on_success()

            # Parse content and function calls
            content_text = ""
            parsed_tool_calls: List[ToolCall] = []

            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text:
                            content_text += part.text
                        if part.function_call:
                            fn_call = part.function_call
                            call_id = f"call_{uuid.uuid4().hex[:8]}"
                            parsed_tool_calls.append(
                                ToolCall(
                                    id=call_id,
                                    name=fn_call.name,
                                    arguments=dict(fn_call.args) if fn_call.args else {},
                                )
                            )

            finish_reason = "stop"
            if parsed_tool_calls:
                finish_reason = "tool_calls"

            usage = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                cached_tokens = self.cache_manager.extract_cached_tokens(response)
                p_tok = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                c_tok = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
                t_tok = getattr(response.usage_metadata, "total_token_count", 0) or 0
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
                content=content_text or None,
                tool_calls=parsed_tool_calls,
                finish_reason=finish_reason,
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
            contents = self._convert_messages(messages)
            gemini_tools = self._convert_tools(tools)

            # Auto-synthesize minimal declarations for historical function calls if tools was omitted,
            # preventing Google GenAI 400 "Tool call not found in tools" during synthesis passes.
            historical_fn_names: Set[str] = set()
            for c in contents:
                if c.parts:
                    for p in c.parts:
                        if p.function_call and p.function_call.name:
                            historical_fn_names.add(p.function_call.name)
                        elif p.function_response and p.function_response.name:
                            historical_fn_names.add(p.function_response.name)

            if historical_fn_names and not gemini_tools:
                synth_decls = [
                    types.FunctionDeclaration(
                        name=fn_name,
                        description=f"Historical tool declaration for {fn_name}",
                        parameters={"type": "object", "properties": {}},
                    )
                    for fn_name in sorted(historical_fn_names)
                ]
                gemini_tools = [types.Tool(function_declarations=synth_decls)]

            tool_config: Optional[types.ToolConfig] = None
            if kwargs.get("tool_choice") == "none" or kwargs.get("force_synthesis") or (tools is None and historical_fn_names):
                tool_config = types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="NONE"
                    )
                )

            cached_content_name = await self._get_or_create_context_cache(
                system_prompt=system_prompt,
                gemini_tools=gemini_tools,
            )

            if cached_content_name:
                config = types.GenerateContentConfig(
                    cached_content=cached_content_name,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    tool_config=tool_config,
                )
            else:
                config = types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    tools=gemini_tools,
                    tool_config=tool_config,
                )

            stream = await client.aio.models.generate_content_stream(
                model=self.config.model,
                contents=contents,
                config=config,
            )

            async for chunk in stream:
                text_delta = ""
                tool_calls: List[ToolCall] = []
                if chunk.candidates:
                    c = chunk.candidates[0]
                    if c.content and c.content.parts:
                        for p in c.content.parts:
                            if p.text:
                                text_delta += p.text
                            if p.function_call:
                                fn = p.function_call
                                tool_calls.append(
                                    ToolCall(
                                        id=f"call_{uuid.uuid4().hex[:8]}",
                                        name=fn.name,
                                        arguments=dict(fn.args) if fn.args else {},
                                    )
                                )

                yield StreamChunk(
                    delta=text_delta,
                    tool_calls=tool_calls if tool_calls else None,
                )

            await self._on_success()

        except Exception as e:
            await self._on_failure(e)
            raise
