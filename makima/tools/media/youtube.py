from typing import Dict, Any

def youtube_control(action: str, video_url: str = "") -> Dict[str, Any]:
    """Control YouTube web player or open video."""
    return {"action": action, "url": video_url, "status": "ok"}
