import os
import httpx
from typing import Dict, Any, AsyncGenerator, List, Optional
from ..base import BaseProvider

class AnthropicAdapter(BaseProvider):
    """Anthropic Claude 3.5 Sonnet adapter with prompt caching support."""
    def __init__(self, model_name: str = "claude-3-5-sonnet-20241022", api_key: str = ""):
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        super().__init__(model_name=model_name, api_key=key)

    async def generate(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "max_tokens": 4096,
            "messages": messages,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            if resp.status_code != 200:
                return {"error": resp.text, "status_code": resp.status_code}
            data = resp.json()
            content_blocks = data.get("content", [])
            text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
            return {"content": text, "raw": data}

    async def stream(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> AsyncGenerator[str, None]:
        res = await self.generate(messages, tools)
        for part in res.get("content", "").split(" "):
            yield part + " "
