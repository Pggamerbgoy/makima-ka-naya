from typing import Dict, Any

def play_song(query: str, service: str = "youtube") -> Dict[str, Any]:
    """Search and play a song or video."""
    return {"query": query, "service": service, "status": "playing"}
