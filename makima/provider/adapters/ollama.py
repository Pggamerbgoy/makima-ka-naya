import httpx
from typing import Dict, Any, AsyncGenerator, List, Optional
from ..base import BaseProvider

class OllamaAdapter(BaseProvider):
    """Ollama local offline model adapter (100% free, zero internet required)."""
    def __init__(self, model_name: str = "qwen2.5-coder", host: str = "http://localhost:11434"):
        super().__init__(model_name=model_name)
        self.host = host.rstrip("/")

    async def generate(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{self.host}/api/chat", json=payload)
                if resp.status_code != 200:
                    return {"error": resp.text, "status_code": resp.status_code}
                data = resp.json()
                return {"content": data.get("message", {}).get("content", ""), "raw": data}
        except Exception as e:
            return {"error": f"Ollama connection error: {e}. Is Ollama running on {self.host}?"}

    async def stream(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> AsyncGenerator[str, None]:
        res = await self.generate(messages, tools)
        for chunk in res.get("content", "").split(" "):
            yield chunk + " "
