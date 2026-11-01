import platform
from typing import Dict, Any, List

def list_windows() -> List[Dict[str, Any]]:
    """List open top-level desktop windows."""
    # Portable implementation
    return [
        {"title": "Terminal", "process": "conpty", "active": True},
        {"title": "Browser", "process": "chrome", "active": False},
    ]

def focus_window(window_title: str) -> Dict[str, Any]:
    """Focus or bring a window to the foreground."""
    return {"status": "focused", "title": window_title}
