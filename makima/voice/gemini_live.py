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

logger = logging.getLogger(__name__)

DEFAULT_LIVE_MODEL = "gemini-3.8-live"


DEFAULT_VOICE_SYSTEM_INSTRUCTION = (
    "You are Makima (in hands-free Jarvis Mode), a brilliant, concise, and helpful personal voice AI. "
    "Speak directly and conversationally without verbose preamble or markdown syntax. "
    "You have full access to all system, media, browser, and developer tools; invoke them directly when needed."
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
        model: str = DEFAULT_LIVE_MODEL,
        voice_name: str = "Aoede",  # Options: Aoede, Charon, Fenrir, Kore, Puck
        system_instruction: Optional[str] = None,
    ) -> None:
        self.settings = get_settings()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or getattr(self.settings, "gemini_api_key", None)
        self.model = model
        self.voice_name = voice_name
        self.system_instruction = system_instruction
        self._client: Optional[genai.Client] = None
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
        # Convert Makima ToolRegistry tools to Gemini function declarations
        reg = get_registry()
        reg.discover()
        schemas = reg.get_schemas()

        function_declarations = []
        for s in schemas:
            fn = s.get("function", {})
            function_declarations.append({
                "name": fn.get("name"),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
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
        self._session = await client.aio.live.connect(model=self.model, config=config)
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

        reg = get_registry()

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

                    # Execute tool via ToolRegistry
                    result = await reg.execute(fn_name, fn_args)
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
        if self._session is not None:
            try:
                await self._session.close()
            except Exception as exc:
                logger.debug("Live session close notice: %s", exc)
        self._is_active = False
        self._session = None
