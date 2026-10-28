"""
Makima v2 — Google GenAI SDK Adapter.
Architectural Pattern: Official google-genai SDK with streaming, function calling, and free-tier optimization.
Zero-Hardcoding Guarantee: Dynamically reads GEMINI_API_KEY and backend config.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

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


class RollingTPMTracker:
    """Sliding-window token bucket preventing live WebSocket sessions from exceeding TPM limits."""

    def __init__(self, max_tpm: int = 55000, window_seconds: float = 60.0):
        self.max_tpm = max_tpm
        self.window_seconds = window_seconds
        self._history: List[Tuple[float, int]] = []
        self._lock = asyncio.Lock()

    async def acquire(self, estimated_tokens: int) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._history = [(t, tok) for t, tok in self._history if now - t < self.window_seconds]
                current_usage = sum(tok for _, tok in self._history)
                if current_usage + estimated_tokens <= self.max_tpm:
                    self._history.append((now, estimated_tokens))
                    return
                oldest_time = self._history[0][0]
                sleep_time = max(0.5, self.window_seconds - (now - oldest_time) + 0.1)
                logger.info(
                    "Live TPM clamp active: %d/%d tokens active in window. Pacing request for %.1fs.",
                    current_usage,
                    self.max_tpm,
                    sleep_time,
                )
                await asyncio.sleep(sleep_time)


_GLOBAL_LIVE_TPM_TRACKER = RollingTPMTracker(max_tpm=55000, window_seconds=60.0)


_ALLOWED_GEMINI_SCHEMA_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "max_items",
    "maxItems",
    "min_items",
    "minItems",
    "properties",
    "required",
    "items",
    "min_length",
    "minLength",
    "max_length",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "default",
    "example",
    "any_of",
    "anyOf",
    "property_ordering",
    "propertyOrdering",
    "defs",
    "ref",
    "title",
}


def _sanitize_gemini_schema(raw: Any) -> Any:
    """
    Recursively purges JSON-schema meta keywords ($schema, $id, $comment, etc.)
    and unsupported attributes that violate Google GenAI's strict types.Schema
    (extra='forbid') constraints.
    """
    if not isinstance(raw, dict):
        return raw

    cleaned: Dict[str, Any] = {}
    for k, v in raw.items():
        norm_k = k
        if k == "$ref":
            norm_k = "ref"
        elif k in ("$defs", "definitions"):
            norm_k = "defs"
        elif k in ("oneOf", "allOf"):
            norm_k = "anyOf"
        elif k.startswith("$"):
            # Purge all JSON-schema meta keywords ($schema, $id, $comment, etc.)
            continue

        if norm_k == "properties" and isinstance(v, dict):
            cleaned["properties"] = {
                str(p_name): _sanitize_gemini_schema(p_val) if isinstance(p_val, dict) else p_val
                for p_name, p_val in v.items()
            }
            continue

        if norm_k == "defs" and isinstance(v, dict):
            cleaned["defs"] = {
                str(d_name): _sanitize_gemini_schema(d_val) if isinstance(d_val, dict) else d_val
                for d_name, d_val in v.items()
            }
            continue

        if norm_k == "items":
            if isinstance(v, dict):
                cleaned["items"] = _sanitize_gemini_schema(v)
            elif isinstance(v, list):
                cleaned["items"] = [
                    _sanitize_gemini_schema(it) if isinstance(it, dict) else it for it in v
                ]
            continue

        if norm_k in ("anyOf", "any_of") and isinstance(v, list):
            cleaned["anyOf"] = [
                _sanitize_gemini_schema(it) if isinstance(it, dict) else it for it in v
            ]
            continue

        if norm_k not in _ALLOWED_GEMINI_SCHEMA_KEYS:
            continue

        if norm_k == "type" and isinstance(v, list):
            # Unpack JSON schema draft union types, e.g. ["string", "null"]
            types_list = [t for t in v if t != "null"]
            if "null" in v:
                cleaned["nullable"] = True
            cleaned["type"] = types_list[0] if types_list else "NULL"
            continue

        if isinstance(v, dict):
            cleaned[norm_k] = _sanitize_gemini_schema(v)
        else:
            cleaned[norm_k] = v

    if "properties" in cleaned and "type" not in cleaned:
        cleaned["type"] = "object"

    return cleaned


def _serialize_declaration_schema(val: Any) -> Any:
    """Safely converts types.Schema or dictionary to a JSON-serializable dictionary for stable hashing."""
    if val is None:
        return {}
    if hasattr(val, "to_json_dict") and callable(val.to_json_dict):
        try:
            return val.to_json_dict()
        except Exception:
            pass
    if hasattr(val, "model_dump") and callable(val.model_dump):
        try:
            return val.model_dump(mode="json", exclude_none=True)
        except Exception:
            pass
    if isinstance(val, dict):
        return {str(k): _serialize_declaration_schema(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_serialize_declaration_schema(x) for x in val]
    return str(val)


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
        self._last_cache_fallback_reason: Optional[str] = None
        self.cache_manager = get_cache_manager()
        self.cache_strategy = CacheStrategy.EXPLICIT_GENAI

    def _get_client(self) -> genai.Client:
        """Lazy initialization of genai.Client with active API key."""
        import os
        api_key = self.config.api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                f"Missing API key for Gemini backend '{self.name}'. "
                f"Ensure environment variable '{self.config.api_key_env or 'GEMINI_API_KEY'}' or 'GOOGLE_API_KEY' is set."
            )
        if self._client is None:
            self._client = genai.Client(api_key=api_key)
        return self._client

    def _convert_tools(self, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[types.Tool]]:
        """Converts standard JSON schema tool definitions into Gemini Tool format with canonical sorting & caching."""
        canonical_tools = canonicalize_tool_schemas(tools)
        if not canonical_tools:
            return None

        # Build stable hash from canonical schemas (including parameters, types, descriptions)
        schema_blob = json.dumps(canonical_tools, sort_keys=True, separators=(",", ":"))
        schema_hash = hashlib.sha256(schema_blob.encode("utf-8")).hexdigest()[:16]

        if self._cached_tools_key == schema_hash and self._cached_tools_payload is not None:
            return self._cached_tools_payload

        declarations = []
        for t in canonical_tools:
            fn = t.get("function", t)
            name = fn.get("name")
            description = fn.get("description", "")
            parameters = fn.get("parameters", {})
            if name:
                clean_params = _sanitize_gemini_schema(parameters)
                try:
                    declarations.append(
                        types.FunctionDeclaration(
                            name=name,
                            description=description,
                            parameters=clean_params,
                        )
                    )
                except Exception as decl_err:
                    logger.warning(
                        "Failed to convert schema for tool '%s' to Gemini FunctionDeclaration: %s. "
                        "Falling back to basic object parameters.",
                        name,
                        decl_err,
                    )
                    try:
                        declarations.append(
                            types.FunctionDeclaration(
                                name=name,
                                description=description,
                                parameters={"type": "object", "properties": {}},
                            )
                        )
                    except Exception:
                        pass

        if not declarations:
            return None
        result = [types.Tool(function_declarations=declarations)]
        self._cached_tools_key = schema_hash
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

        # Build stable JSON canonical representation for function declarations
        tools_summary = []
        if gemini_tools:
            for t in gemini_tools:
                for fd in (getattr(t, "function_declarations", None) or []):
                    params = getattr(fd, "parameters", None)
                    tools_summary.append({
                        "name": getattr(fd, "name", ""),
                        "description": getattr(fd, "description", "") or "",
                        "parameters": _serialize_declaration_schema(params),
                    })

        tools_blob = json.dumps(tools_summary, sort_keys=True, separators=(",", ":"))
        cache_seed = f"{self.config.model}:{system_prompt or ''}:{tools_blob}"
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
            self._last_cache_fallback_reason = str(exc)
            logger.info("Gemini KV Context Caching fallback to standard prompt for model %s: %s", self.config.model, exc)

        return None

    def _is_live_model(self) -> bool:
        """Determines if target model requires bidiGenerateContent WebSocket connection."""
        model_name = str(self.config.model or "").lower()
        return "live" in model_name or "bidi" in model_name

    def _clean_live_schema(self, d: Any) -> Any:
        """Sanitizes schema specifically for Gemini Live WebSocket API constraints."""
        if not isinstance(d, dict):
            return d
        out = {}
        for k, v in d.items():
            if k in ("additionalProperties", "additional_properties", "$schema", "$id", "$comment", "$defs", "definitions"):
                continue
            if k == "title" and isinstance(v, str):
                continue
            if k == "properties" and isinstance(v, dict):
                out["properties"] = {pk: self._clean_live_schema(pv) for pk, pv in v.items()}
                continue
            if isinstance(v, dict):
                out[k] = self._clean_live_schema(v)
            elif isinstance(v, list):
                out[k] = [self._clean_live_schema(x) if isinstance(x, dict) else x for x in v]
            else:
                out[k] = v
        if "properties" in out and "type" not in out:
            out["type"] = "object"
        return out

    async def _generate_live(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> ProviderResponse:
        """Executes full-duplex WebSocket Live turn for models that require bidiGenerateContent."""
        start_time = time.monotonic()
        client = self._get_client()

        function_declarations = []
        if tools:
            canonical_tools = canonicalize_tool_schemas(tools) or []
            for t in canonical_tools:
                fn = t.get("function", t)
                name = fn.get("name")
                description = fn.get("description", "")
                parameters = fn.get("parameters", {})
                if name:
                    clean_params = self._clean_live_schema(_sanitize_gemini_schema(parameters))
                    function_declarations.append({
                        "name": name,
                        "description": description,
                        "parameters": clean_params,
                    })

        thinking_cfg = None
        model_lower = str(self.config.model or "").lower()
        if "extended-thinking" in model_lower:
            thinking_cfg = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)

        tools_config = [types.Tool(function_declarations=function_declarations)] if function_declarations else None
        live_config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=tools_config,
            system_instruction=system_prompt,
            thinking_config=thinking_cfg,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede"))
            ),
        )

        # Apply sliding window TPM protection before opening WebSocket
        est_tokens = len(system_prompt or "") // 3 + len(function_declarations) * 90 + 200
        await _GLOBAL_LIVE_TPM_TRACKER.acquire(est_tokens)

        cm = client.aio.live.connect(model=self.config.model, config=live_config)
        session = await cm.__aenter__()
        try:
            recent_context = []
            for m in messages:
                if m.role == "user" and m.content:
                    recent_context.append(f"User: {m.content}")
                elif m.role == "assistant":
                    if m.content:
                        recent_context.append(f"Assistant: {m.content}")
                    elif m.tool_calls:
                        c_str = ", ".join(f"{c.name}({json.dumps(c.arguments or {})})" for c in m.tool_calls)
                        recent_context.append(f"Assistant invoked tool: {c_str}")
                elif m.role == "tool":
                    tool_desc = f"Tool Result ({m.name or getattr(m, 'tool_call_id', 'tool')})"
                    recent_context.append(f"{tool_desc}: {m.content[:1500]}")

            last_msg = messages[-1] if messages else None
            if last_msg and last_msg.role == "tool":
                full_prompt = (
                    "Here is the ongoing conversation and latest tool execution results:\n"
                    + "\n".join(recent_context[-8:])
                    + "\n\nPlease provide your response or next tool call based on these results."
                )
            elif recent_context and len(recent_context) > 1:
                history_str = "\n".join(recent_context[:-1][-6:])
                curr_req = (last_msg.content if last_msg else "") or ""
                full_prompt = f"Previous conversation:\n{history_str}\n\nCurrent user request: {curr_req}"
            else:
                full_prompt = (last_msg.content if last_msg else "") or "Hello"

            await session.send(input=full_prompt, end_of_turn=True)

            content_pieces: List[str] = []
            tool_calls: List[ToolCall] = []

            async for resp in session.receive():
                sc = getattr(resp, "server_content", None)
                if sc:
                    ot = getattr(sc, "output_transcription", None)
                    if ot and getattr(ot, "text", None):
                        content_pieces.append(ot.text)
                tc = getattr(resp, "tool_call", None)
                if tc:
                    for fc in getattr(tc, "function_calls", []):
                        call_id = getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:8]}"
                        fn_name = fc.name.split(":")[-1] if ":" in fc.name else fc.name
                        args = dict(fc.args) if hasattr(fc, "args") else {}
                        tool_calls.append(ToolCall(id=call_id, name=fn_name, arguments=args))
                    break
                if sc and getattr(sc, "turn_complete", False):
                    break

            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            return ProviderResponse(
                content="".join(content_pieces).strip(),
                tool_calls=tool_calls,
                finish_reason="tool_calls" if tool_calls else "stop",
                model=self.config.model,
                latency_ms=elapsed_ms,
            )
        finally:
            await cm.__aexit__(None, None, None)

    async def _stream_live(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Streams text chunks in real-time from bidi WebSocket live session."""
        client = self._get_client()

        function_declarations = []
        if tools:
            canonical_tools = canonicalize_tool_schemas(tools) or []
            for t in canonical_tools:
                fn = t.get("function", t)
                name = fn.get("name")
                description = fn.get("description", "")
                parameters = fn.get("parameters", {})
                if name:
                    clean_params = self._clean_live_schema(_sanitize_gemini_schema(parameters))
                    function_declarations.append({
                        "name": name,
                        "description": description,
                        "parameters": clean_params,
                    })

        thinking_cfg = None
        model_lower = str(self.config.model or "").lower()
        if "extended-thinking" in model_lower:
            thinking_cfg = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)

        tools_config = [types.Tool(function_declarations=function_declarations)] if function_declarations else None
        live_config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=tools_config,
            system_instruction=system_prompt,
            thinking_config=thinking_cfg,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede"))
            ),
        )

        # Apply sliding window TPM protection before opening WebSocket
        est_tokens = len(system_prompt or "") // 3 + len(function_declarations) * 90 + 200
        await _GLOBAL_LIVE_TPM_TRACKER.acquire(est_tokens)

        cm = client.aio.live.connect(model=self.config.model, config=live_config)
        session = await cm.__aenter__()
        try:
            recent_context = []
            for m in messages:
                if m.role == "user" and m.content:
                    recent_context.append(f"User: {m.content}")
                elif m.role == "assistant":
                    if m.content:
                        recent_context.append(f"Assistant: {m.content}")
                    elif m.tool_calls:
                        c_str = ", ".join(f"{c.name}({json.dumps(c.arguments or {})})" for c in m.tool_calls)
                        recent_context.append(f"Assistant invoked tool: {c_str}")
                elif m.role == "tool":
                    tool_desc = f"Tool Result ({m.name or getattr(m, 'tool_call_id', 'tool')})"
                    recent_context.append(f"{tool_desc}: {m.content[:1500]}")

            last_msg = messages[-1] if messages else None
            if last_msg and last_msg.role == "tool":
                full_prompt = (
                    "Here is the ongoing conversation and latest tool execution results:\n"
                    + "\n".join(recent_context[-8:])
                    + "\n\nPlease provide your response or next tool call based on these results."
                )
            elif recent_context and len(recent_context) > 1:
                history_str = "\n".join(recent_context[:-1][-6:])
                curr_req = (last_msg.content if last_msg else "") or ""
                full_prompt = f"Previous conversation:\n{history_str}\n\nCurrent user request: {curr_req}"
            else:
                full_prompt = (last_msg.content if last_msg else "") or "Hello"

            await session.send(input=full_prompt, end_of_turn=True)

            async for resp in session.receive():
                sc = getattr(resp, "server_content", None)
                if sc:
                    ot = getattr(sc, "output_transcription", None)
                    if ot and getattr(ot, "text", None):
                        yield StreamChunk(delta=ot.text, model=self.config.model)
                tc = getattr(resp, "tool_call", None)
                if tc:
                    tool_calls: List[ToolCall] = []
                    for fc in getattr(tc, "function_calls", []):
                        call_id = getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:8]}"
                        fn_name = fc.name.split(":")[-1] if ":" in fc.name else fc.name
                        args = dict(fc.args) if hasattr(fc, "args") else {}
                        tool_calls.append(ToolCall(id=call_id, name=fn_name, arguments=args))
                    yield StreamChunk(delta="", tool_calls=tool_calls, finish_reason="tool_calls", model=self.config.model)
                    break
                if sc and getattr(sc, "turn_complete", False):
                    yield StreamChunk(delta="", finish_reason="stop", model=self.config.model)
                    break
        finally:
            await cm.__aexit__(None, None, None)

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

        if self._is_live_model():
            try:
                res = await self._generate_live(
                    messages=messages,
                    tools=tools,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                await self._on_success()
                return res
            except Exception as e:
                await self._on_failure(e)
                raise

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
        if self._is_live_model():
            async for chunk in self._stream_live(
                messages=messages,
                tools=tools,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            ):
                yield chunk
            return
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
