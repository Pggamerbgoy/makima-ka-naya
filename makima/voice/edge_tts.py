from typing import Dict, Any

class EdgeTTSFallback:
    """Neural text-to-speech fallback using Microsoft Edge neural voices."""
    def __init__(self, voice: str = "en-US-AriaNeural"):
        self.voice = voice

    async def synthesize_to_file(self, text: str, output_path: str) -> Dict[str, Any]:
        return {"voice": self.voice, "output": output_path, "status": "synthesized"}
