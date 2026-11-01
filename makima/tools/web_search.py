import httpx
from typing import Dict, Any, List

async def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search open knowledge bases and web APIs for real-time citations and facts."""
    url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit={max_results}&namespace=0&format=json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                titles = data[1] if len(data) > 1 else []
                snippets = data[2] if len(data) > 2 else []
                links = data[3] if len(data) > 3 else []
                results = [{"title": t, "snippet": s, "url": l} for t, s, l in zip(titles, snippets, links)]
                return {"query": query, "results": results or [{"snippet": f"No direct entry found for '{query}'."}]}
    except Exception as e:
        return {"query": query, "error": str(e), "results": []}
    return {"query": query, "results": []}
