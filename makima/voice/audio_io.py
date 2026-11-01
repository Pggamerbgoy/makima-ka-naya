from typing import Dict, Any

class AudioIOManager:
    """Sounddevice microphone input capture and speaker output streams."""
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def start_recording(self):
        pass

    def stop_recording(self) -> bytes:
        return b""
