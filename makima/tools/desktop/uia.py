from typing import Dict, Any, List

class UIAutomationReader:
    """Windows UI Automation tree inspector."""
    def inspect_tree(self) -> List[Dict[str, Any]]:
        return [
            {"type": "Window", "name": "Desktop", "children": []}
        ]
