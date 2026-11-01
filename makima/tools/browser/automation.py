import httpx
from typing import Dict, Any

class BrowserController:
    """Headless browser automation and clean web content extraction."""
    def __init__(self, headless: bool = True):
        self.headless = headless

    async def navigate_and_extract(self, url: str) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url)
                return {
                    "url": url,
                    "status_code": resp.status_code,
                    "text_content": resp.text[:4000],
                }
        except Exception as e:
            return {"url": url, "error": str(e)}
