"""
Makima v2 — Voice Subsystem.
Powered exclusively by Gemini 3.8 Live Bidirectional Multimodal Voice.
Zero standalone TTS dependencies.
"""

from makima.voice.audio_io import AudioIO
from makima.voice.controller import LiveVoiceController
from makima.voice.gemini_live import GeminiLiveSession

__all__ = [
    "AudioIO",
    "GeminiLiveSession",
    "LiveVoiceController",
]
