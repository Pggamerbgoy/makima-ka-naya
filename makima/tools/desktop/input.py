from typing import Dict, Any

def mouse_click(x: int, y: int, button: str = "left") -> Dict[str, Any]:
    """Click coordinate on the screen."""
    return {"action": "click", "x": x, "y": y, "button": button, "status": "ok"}

def key_press(key: str) -> Dict[str, Any]:
    """Press keyboard key or shortcut combination."""
    return {"action": "key_press", "key": key, "status": "ok"}
