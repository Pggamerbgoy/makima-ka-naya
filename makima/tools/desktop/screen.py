from typing import Dict, Any

def capture_screenshot(region: tuple = None) -> Dict[str, Any]:
    """Capture full screen or specific bounding box region."""
    return {"status": "captured", "format": "png", "region": region}
