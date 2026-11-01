from typing import Dict, Any

def spotify_control(action: str) -> Dict[str, Any]:
    """Control Spotify desktop or web player."""
    return {"service": "spotify", "action": action, "status": "ok"}
