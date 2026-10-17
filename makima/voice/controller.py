"""
Makima v2 — Gemini Live Native Voice Controller.
Architectural Pattern: Full-duplex microphone-to-Gemini-to-speaker pipeline.
Strict Mandate: Zero standalone TTS. Uses Gemini Live's native bidirectional audio generation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

import numpy as np
import sounddevice as sd

from makima.voice.audio_io import AudioIO
from makima.voice.gemini_live import GeminiLiveSession

logger = logging.getLogger(__name__)


class LiveVoiceController:
    """
    Coordinates full-duplex live conversation with Gemini Live:
    - Streams microphone PCM chunks directly to Gemini Live API.
    - Streams Gemini's generated audio directly to speakers.
    - Handles barge-in / speech interruption: stops speaker playback immediately when user speaks.
    - Zero TTS dependencies.
    """

    def __init__(
        self,
        session: Optional[GeminiLiveSession] = None,
        voice_name: str = "Aoede",  # Options: Aoede, Charon, Fenrir, Kore, Puck
        on_status: Optional[Callable[[str, Any], None]] = None,
    ) -> None:
        self.session = session or GeminiLiveSession(voice_name=voice_name)
        self.on_status = on_status
        self._is_running = False
        self._mic_stream: Optional[sd.InputStream] = None
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _mic_callback(self, indata, frames, time_info, status):
        """Called by sounddevice InputStream in real-time."""
        if status:
            logger.debug("Microphone status notice: %s", status)
        if self._is_running:
            raw_bytes = indata.tobytes()
            # Barge-in volume threshold check: if user speaks loudly while playing, halt speaker
            volume_norm = np.linalg.norm(indata) / np.sqrt(frames)
            if volume_norm > 500:  # Active speech detected
                AudioIO.stop_playback()

            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._audio_queue.put_nowait, raw_bytes)
            else:
                self._audio_queue.put_nowait(raw_bytes)

    async def _send_mic_worker(self) -> None:
        """Pulls audio chunks from queue and sends them to Gemini Live."""
        while self._is_running:
            try:
                chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=0.5)
                if self.session.is_active:
                    await self.session.send_audio_chunk(chunk)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                if self._is_running:
                    logger.debug("Send mic chunk notice: %s", exc)

    async def _receive_events_worker(self) -> None:
        """Receives Gemini Live audio output and in-stream tool executions."""
        try:
            async for event in self.session.receive_events():
                if not self._is_running:
                    break

                ev_type = event.get("type")

                if ev_type == "audio":
                    # Play native Gemini Live audio chunk through speakers
                    pcm_data = event.get("data")
                    if pcm_data:
                        AudioIO.play_pcm_chunk(pcm_data)
                    if self.on_status:
                        self.on_status("audio_chunk", len(pcm_data or b""))

                elif ev_type == "text":
                    # Real-time transcript chunk
                    if self.on_status:
                        self.on_status("transcript", event.get("text", ""))

                elif ev_type == "tool_call":
                    if self.on_status:
                        self.on_status("tool_call", event)

                elif ev_type == "tool_result":
                    if self.on_status:
                        self.on_status("tool_result", event)

                elif ev_type in ("turn_complete", "interrupted"):
                    if self.on_status:
                        self.on_status(ev_type, event)

        except Exception as exc:
            if self._is_running:
                logger.error("Receive events worker error: %s", exc)

    async def start(self) -> None:
        """Starts live microphone capture and connects to Gemini Live session."""
        self._loop = asyncio.get_running_loop()
        self._is_running = True

        # 1. Connect to Gemini Live API
        if not self.session.is_active:
            await self.session.connect()

        # 2. Start microphone input stream
        try:
            self._mic_stream = sd.InputStream(
                samplerate=AudioIO.DEFAULT_INPUT_RATE,
                channels=1,
                dtype="int16",
                blocksize=1024,
                callback=self._mic_callback,
            )
            self._mic_stream.start()
        except Exception as exc:
            logger.warning("Could not open microphone stream (running in test/headless mode?): %s", exc)

        logger.info("Gemini Live Voice Controller active (Model native audio, Zero TTS)")

        # 3. Launch concurrent send and receive tasks
        self._tasks = [
            asyncio.create_task(self._send_mic_worker()),
            asyncio.create_task(self._receive_events_worker()),
        ]

    async def stop(self) -> None:
        """Cleanly stops voice session and hardware streams."""
        self._is_running = False
        AudioIO.stop_playback()

        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception as exc:
                logger.debug("Mic stream stop notice: %s", exc)
            self._mic_stream = None

        if hasattr(self, "_tasks"):
            for t in self._tasks:
                t.cancel()

        await self.session.close()
        logger.info("Gemini Live Voice Controller stopped.")
