from typing import List, Dict, Any

class ContextCompressor:
    """Middle-out context compression when conversation approaches model token budget."""
    def __init__(self, target_ratio: float = 0.6):
        self.target_ratio = target_ratio

    def compress(self, messages: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
        if len(messages) <= 4:
            return messages
        # Retain head (system) and tail (recent turns)
        head = messages[:2]
        tail = messages[-2:]
        summary_node = {
            "role": "system",
            "content": f"[Context Compressed: {len(messages) - 4} intermediate turns synthesized into memory context]"
        }
        return head + [summary_node] + tail
