"""
Makima v2 — Voice subsystem public API.

Hardware-dependent microphone and speaker components are imported lazily so
browser-hosted Gemini Live voice can run without local PortAudio hardware.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AudioIO",
    "GeminiLiveSession",
    "LiveVoiceController",
]


def __getattr__(name: str) -> Any:
    """Lazily resolve voice components; local audio dependencies are optional."""
    if name == "AudioIO":
        from makima.voice.audio_io import AudioIO
        return AudioIO
    if name == "GeminiLiveSession":
        from makima.voice.gemini_live import GeminiLiveSession
        return GeminiLiveSession
    if name == "LiveVoiceController":
        from makima.voice.controller import LiveVoiceController
        return LiveVoiceController
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
