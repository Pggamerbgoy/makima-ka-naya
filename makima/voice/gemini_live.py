"""
Makima v2 — Gemini Live Bidirectional Multimodal Audio Stream.
Architectural Pattern: Full-duplex WebSocket stream using google-genai SDK.
Zero-Hardcoding Guarantee: Dynamic credential resolution and live tool registration.
"""

from __future__ import annotations

import logging
import os
from typing import Any, AsyncIterator, Dict, Optional

import google.genai as genai
from google.genai import types

from makima.config import get_settings
from makima.tools.registry import get_registry
from makima.tools.selection import ToolExecutionGateway

logger = logging.getLogger(__name__)


def sanitize_gemini_live_schema(raw: Any) -> Any:
    """
    Sanitizes JSON schemas specifically for strict Gemini Live WebSocket API.
    Purges additionalProperties, $schema, and unneeded meta attributes that
    cause Gemini Live bidiGenerateContent setup errors.
    """
    if not isinstance(raw, dict):
        return raw

    cleaned: Dict[str, Any] = {}
    for k, v in raw.items():
        if k in ("additionalProperties", "additional_properties", "$schema", "$id", "$comment", "$defs", "definitions"):
            continue
        if k == "title" and isinstance(v, str):
            continue
        if k == "properties" and isinstance(v, dict):
            cleaned["properties"] = {
                p_name: sanitize_gemini_live_schema(p_val)
                for p_name, p_val in v.items()
            }
            continue
        if isinstance(v, dict):
            cleaned[k] = sanitize_gemini_live_schema(v)
        elif isinstance(v, list):
            cleaned[k] = [sanitize_gemini_live_schema(x) if isinstance(x, dict) else x for x in v]
        else:
            cleaned[k] = v

    if "properties" in cleaned and "type" not in cleaned:
        cleaned["type"] = "object"

    return cleaned


def get_live_model() -> str:
    """
    Dynamically resolves the Live API model without hardcoding.
    Priority:
    1. Environment variable (MAKIMA_LIVE_MODEL / GEMINI_LIVE_MODEL / MAKIMA_VOICE__MODEL)
    2. settings.yaml (voice.model)
    3. Fallback default ('gemini-3.8-live')
    """
    try:
        settings = get_settings()
        voice_cfg = getattr(settings, "voice", None)
        cfg_model = getattr(voice_cfg, "model", None) if voice_cfg else None
    except Exception:
        cfg_model = None

    return (
        os.getenv("MAKIMA_LIVE_MODEL")
        or os.getenv("GEMINI_LIVE_MODEL")
        or os.getenv("MAKIMA_VOICE__MODEL")
        or cfg_model
        or "gemini-3.8-live"
    )


def get_voice_name() -> str:
    """
    Dynamically resolves the Live voice persona without hardcoding.
    Options: Aoede, Charon, Fenrir, Kore, Puck.
    """
    try:
        settings = get_settings()
        voice_cfg = getattr(settings, "voice", None)
        cfg_voice = getattr(voice_cfg, "voice_name", None) if voice_cfg else None
    except Exception:
        cfg_voice = None

    return (
        os.getenv("MAKIMA_VOICE_NAME")
        or os.getenv("MAKIMA_VOICE__VOICE_NAME")
        or cfg_voice
        or "Aoede"
    )


DEFAULT_LIVE_MODEL = "gemini-3.8-live"


DEFAULT_VOICE_SYSTEM_INSTRUCTION = (
    "You are Makima (in hands-free Jarvis Mode), a brilliant, concise, and proactive personal voice AI. "
    "Speak directly and conversationally without verbose preamble or markdown syntax. "
    "You have full access to all system, media, browser, and developer tools; invoke them directly when needed.\n"
    "SEMANTIC PROACTIVITY RULES:\n"
    "1. When you receive a '[SYSTEM_EVENT]' text prompt from the OS sentinel containing sanitized ambient context "
    "(such as clipboard text, downloaded file metadata, or memory metrics), use your reasoning to evaluate user intent.\n"
    "2. If the context represents an actionable task (e.g. tracking a package, organizing an invoice, scheduling a meeting, or freeing RAM), "
    "proactively invoke the appropriate tool or speak a brief 1-sentence helpful update.\n"
    "3. If the event is irrelevant, casual chat, or non-actionable, REMAIN COMPLETELY SILENT (produce no output and call no tools).\n"
    "4. Spoken updates must be natural, brief, and never recite long codes or file paths aloud.\n"
    "MEDIA TOOL SELECTION RULES:\n"
    "- Use play_song only for songs, artists, playlists, albums, or audio tracks (or an explicitly supplied local media file). Never use it to search for online anime episodes, TV series, movies, AMVs, trailers, or other videos.\n"
    "- For online anime/video viewing, use browser_interact. Prefer the explicitly requested website; otherwise honor the user's saved streaming-site preference (for example, Miruro when saved in memory). Search the title and select the requested episode.\n"
    "- Do not default anime/video requests to YouTube unless the user explicitly requests YouTube or it is the saved preference for that request. Do not claim playback began unless the tool result verifies it."
)


class GeminiLiveSession:
    """
    Manages a real-time full-duplex WebSocket session with Gemini Live API.
    Supports continuous 16kHz PCM audio streaming, barge-in detection,
    and in-stream tool execution via Makima's ToolRegistry.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        voice_name: Optional[str] = None,
        system_instruction: Optional[str] = None,
        execution_gateway: Optional[ToolExecutionGateway] = None,
    ) -> None:
        self.settings = get_settings()
        backend_key = None
        if hasattr(self.settings, "providers") and hasattr(self.settings.providers, "backends"):
            g_backend = self.settings.providers.backends.get("gemini")
            if g_backend:
                backend_key = getattr(g_backend, "api_key", None)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or backend_key
        self.model = model or get_live_model()
        self.voice_name = voice_name or get_voice_name()
        self.system_instruction = system_instruction
        self.execution_gateway = execution_gateway
        self._available_tool_names: set[str] = set()
        self._client: Optional[genai.Client] = None
        self._cm: Optional[Any] = None
        self._session: Optional[Any] = None
        self._is_active = False

    @property
    def is_active(self) -> bool:
        return self._is_active

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is required to establish a Gemini Live session.")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _build_live_config(self) -> types.LiveConnectConfig:
        """Constructs LiveConnectConfig with audio modality, prompt, and registered tools."""
        if self.execution_gateway is None:
            self.execution_gateway = ToolExecutionGateway(get_registry())
        reg = self.execution_gateway.registry
        reg.discover()
        schemas = self.execution_gateway.get_schemas(format="openai")
        self._available_tool_names = {
            str(s.get("function", {}).get("name"))
            for s in schemas
            if isinstance(s.get("function"), dict) and s.get("function", {}).get("name")
        }

        function_declarations = []
        for s in schemas:
            fn = s.get("function", {})
            params = sanitize_gemini_live_schema(fn.get("parameters", {}))
            function_declarations.append({
                "name": fn.get("name"),
                "description": fn.get("description", ""),
                "parameters": params,
            })

        speech_config = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=self.voice_name,
                )
            )
        )

        tools_config = [types.Tool(function_declarations=function_declarations)] if function_declarations else None

        realtime_input_config = types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                silence_duration_ms=1200,
                prefix_padding_ms=300,
            )
        )

        context_window_compression = types.ContextWindowCompressionConfig(
            trigger_tokens=8192,
            sliding_window=types.SlidingWindow(target_tokens=4096),
        ) if hasattr(types, "ContextWindowCompressionConfig") else None

        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=speech_config,
            tools=tools_config,
            realtime_input_config=realtime_input_config,
            system_instruction=self.system_instruction or DEFAULT_VOICE_SYSTEM_INSTRUCTION,
            context_window_compression=context_window_compression,
        )

    async def connect(self) -> Any:
        """Establishes full-duplex session connection."""
        client = self._get_client()
        config = self._build_live_config()
        self._cm = client.aio.live.connect(model=self.model, config=config)
        self._session = await self._cm.__aenter__()
        self._is_active = True
        logger.info("Connected to Gemini Live session (model: %s, voice: %s)", self.model, self.voice_name)
        return self._session

    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        """Sends raw 16kHz PCM audio frame into the live session."""
        if not self._is_active or self._session is None:
            raise RuntimeError("Live session is not active. Call connect() first.")

        await self._session.send(
            input=types.LiveClientRealtimeInput(
                media_chunks=[
                    types.Blob(
                        data=pcm_bytes,
                        mime_type="audio/pcm;rate=16000",
                    )
                ]
            )
        )

    async def send_text_prompt(self, text: str, end_of_turn: bool = True) -> None:
        """Sends a text message into the live stream."""
        if not self._is_active or self._session is None:
            raise RuntimeError("Live session is not active.")

        await self._session.send(
            input=types.Content(
                parts=[types.Part.from_text(text=text)],
            ),
            end_of_turn=end_of_turn,
        )

    async def receive_events(self) -> AsyncIterator[Dict[str, Any]]:
        """
        Listens to downstream live server events, yielding audio bytes,
        text transcripts, or executing and returning tool calls.
        """
        if not self._is_active or self._session is None:
            raise RuntimeError("Live session is not active.")

        # Use the exact gateway/registry whose schemas were exposed to Gemini.
        # This preserves disabled-tool checks, per-session allowlists, and shared guardrails.
        if self.execution_gateway is None:
            self.execution_gateway = ToolExecutionGateway(get_registry())
        gateway = self.execution_gateway

        async for response in self._session.receive():
            server_content = getattr(response, "server_content", None)
            if server_content is not None:
                model_turn = getattr(server_content, "model_turn", None)
                if model_turn:
                    for part in model_turn.parts:
                        # Audio chunk received
                        if getattr(part, "inline_data", None):
                            yield {
                                "type": "audio",
                                "data": part.inline_data.data,
                                "mime_type": part.inline_data.mime_type,
                            }
                        # Text transcript chunk received
                        elif getattr(part, "text", None):
                            yield {
                                "type": "text",
                                "text": part.text,
                            }

                if getattr(server_content, "turn_complete", False):
                    yield {"type": "turn_complete"}
                if getattr(server_content, "interrupted", False):
                    yield {"type": "interrupted"}

            # In-stream tool call handling
            tool_call = getattr(response, "tool_call", None)
            if tool_call is not None:
                function_calls = getattr(tool_call, "function_calls", [])
                function_responses = []

                for fc in function_calls:
                    fn_name = fc.name
                    fn_args = dict(fc.args) if hasattr(fc, "args") else {}
                    yield {
                        "type": "tool_call",
                        "name": fn_name,
                        "args": fn_args,
                        "call_id": getattr(fc, "id", None),
                    }

                    # Execute only tools declared for this live session through the
                    # shared gateway. Direct registry execution bypasses disabled state and guardrails.
                    result = await gateway.execute(
                        fn_name,
                        fn_args,
                        allowed_tool_names=self._available_tool_names,
                    )
                    yield {
                        "type": "tool_result",
                        "name": fn_name,
                        "result": result,
                    }

                    function_responses.append(
                        types.FunctionResponse(
                            name=fn_name,
                            id=getattr(fc, "id", None),
                            response={"result": result},
                        )
                    )

                # Return tool output to the live session
                if function_responses:
                    await self._session.send(
                        input=types.LiveClientToolResponse(
                            function_responses=function_responses,
                        )
                    )

    async def close(self) -> None:
        """Closes the live audio session cleanly."""
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("Live session exit notice: %s", exc)
        self._cm = None
        self._session = None
        self._is_active = False
