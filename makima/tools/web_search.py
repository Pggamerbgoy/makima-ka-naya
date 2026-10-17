"""
Makima v2 — Fast Web Search & Page Fetch Tools (Step 22).
Architectural Pattern: High-precision Tavily Search + Resilient DuckDuckGo HTML Fallback.
Connection Pooling: Centralized loop-aware HTTP/2 connection pool from makima.core.http_pool.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup
from tavily import AsyncTavilyClient

from makima.core.http_pool import get_shared_client
from makima.tools.registry import tool

logger = logging.getLogger("makima.tools.web_search")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _get_tavily_api_key() -> Optional[str]:
    """
    Dynamically probes for Tavily API key from environment, .env file,
    or user profile configuration (~/.tavily/config.json).
    """
    key = os.getenv("TAVILY_API_KEY")
    if key and key.strip():
        return key.strip()

    # Check project .env
    for env_path in (Path(".env"), Path(__file__).resolve().parent.parent.parent / ".env"):
        if env_path.is_file():
            try:
                from dotenv import dotenv_values
                env_vals = dotenv_values(str(env_path))
                k = env_vals.get("TAVILY_API_KEY")
                if k and k.strip():
                    return k.strip()
            except Exception:
                pass

    # Check user config (~/.tavily/config.json)
    config_file = Path.home() / ".tavily" / "config.json"
    if config_file.is_file():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                k = data.get("api_key")
                if k and k.strip():
                    return k.strip()
        except Exception:
            pass

    return None


def _clean_text(text: str) -> str:
    """Strips excess whitespace and normalizes newlines."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@tool(
    name="web_search",
    description=(
        "Search the web for current information. Returns up to max_results structured results "
        "with title, URL, and snippet. Use for finding facts, documentation, news, or any "
        "information not in your training data. Faster than browser automation."
    ),
    tags=["web", "search", "internet", "research"],
)
async def web_search(
    query: str,
    max_results: int = 5,
    timelimit: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fast web search using Tavily Search API with DuckDuckGo HTML fallback.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return (1-10).
        timelimit: Optional time filter: 'd' (day), 'w' (week), 'm' (month), 'y' (year).

    Returns:
        List of dicts: [{title, url, snippet}] ordered by relevance.
    """
    if not query or not query.strip():
        return []

    max_results = max(1, min(10, max_results))
    results: List[Dict[str, Any]] = []

    # 1. Primary: Tavily Web Search if API key is configured
    tavily_key = _get_tavily_api_key()
    if tavily_key:
        try:
            time_range_map = {"d": "day", "w": "week", "m": "month", "y": "year"}
            time_range = time_range_map.get(timelimit) if timelimit in time_range_map else None

            tavily_client = AsyncTavilyClient(api_key=tavily_key)
            tavily_res = await tavily_client.search(
                query=query.strip(),
                max_results=max_results,
                time_range=time_range,
            )

            for r in tavily_res.get("results", []):
                title = _clean_text(r.get("title", ""))
                url = str(r.get("url", "")).strip()
                snippet = _clean_text(r.get("content", ""))
                if title and url:
                    results.append({
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                    })
                if len(results) >= max_results:
                    break

            if results:
                logger.debug(f"web_search via Tavily('{query}') → {len(results)} results")
                return results

        except Exception as e:
            logger.warning(f"Tavily search failed, falling back to DuckDuckGo: {e}")

    # 2. Resilient Fallback: DuckDuckGo HTML search via centralized http_pool
    try:
        client = await get_shared_client()
        df = timelimit if timelimit in ("d", "w", "m", "y") else None

        post_data = {"q": query.strip(), "kl": "us-en"}
        if df:
            post_data["df"] = df

        resp = await client.post(
            "https://html.duckduckgo.com/html/",
            data=post_data,
            headers=_HEADERS,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&kl=us-en"
            if df:
                url += f"&df={df}"
            resp = await client.get(
                url,
                headers=_HEADERS,
                follow_redirects=True,
            )

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for result_div in soup.select(".result__body"):
                if len(results) >= max_results:
                    break

                title_tag = result_div.select_one(".result__title")
                link_tag = result_div.select_one(".result__url")
                snippet_tag = result_div.select_one(".result__snippet")

                if not title_tag:
                    continue

                title = _clean_text(title_tag.get_text())
                snippet = _clean_text(snippet_tag.get_text()) if snippet_tag else ""

                anchor = title_tag.select_one("a")
                href = anchor.get("href", "") if anchor else ""
                if "uddg=" in href:
                    parsed = urlparse(href)
                    uddg = parse_qs(parsed.query).get("uddg", [""])[0]
                    href = uddg if uddg else href
                elif link_tag:
                    href = "https://" + _clean_text(link_tag.get_text())

                if not href or not title:
                    continue

                results.append({
                    "title": title,
                    "url": href,
                    "snippet": snippet,
                })

        logger.debug(f"web_search via DDG fallback('{query}') → {len(results)} results")
        return results

    except Exception as e:
        logger.warning(f"web_search failed: {e}")
        return [{"title": "Search failed", "url": "", "snippet": str(e)}]


@tool(
    name="fetch_page",
    description=(
        "Fetch and read the text content of a URL. Much faster than browser automation — "
        "use for reading documentation, articles, or pages that don't require JavaScript. "
        "Returns clean extracted text, not raw HTML."
    ),
    tags=["web", "fetch", "read", "scrape"],
)
async def fetch_page(
    url: str,
    extract_text: bool = True,
    max_chars: int = 8000,
) -> Dict[str, Any]:
    """
    Fetches a URL and extracts readable text content using shared connection pool.

    Args:
        url: The URL to fetch.
        extract_text: If True, extract clean text. If False, return raw HTML snippet.
        max_chars: Maximum characters to return (default 8000 to fit in context).

    Returns:
        Dict with: {url, title, text, status_code, error}
    """
    if not url or not url.strip():
        return {"url": url, "title": "", "text": "", "status_code": 0, "error": "Empty URL"}

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    client = await get_shared_client()

    try:
        resp = await client.get(url, headers=_HEADERS, follow_redirects=True)
        status = resp.status_code

        if status >= 400:
            return {
                "url": url,
                "title": "",
                "text": "",
                "status_code": status,
                "error": f"HTTP {status}",
            }

        content_type = resp.headers.get("content-type", "")
        if "html" not in content_type and "text" not in content_type:
            return {
                "url": url,
                "title": "",
                "text": f"[Non-text content: {content_type}]",
                "status_code": status,
                "error": None,
            }

        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.find("title")
        title = _clean_text(title_tag.get_text()) if title_tag else ""

        if not extract_text:
            raw = resp.text[:max_chars]
            return {"url": url, "title": title, "text": raw, "status_code": status, "error": None}

        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        main = soup.find("main") or soup.find("article") or soup.find(id="content") or soup.body
        if main:
            text = main.get_text(separator="\n")
        else:
            text = soup.get_text(separator="\n")

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[… truncated at {max_chars} chars]"

        logger.debug(f"fetch_page('{url}') → {len(text)} chars")
        return {"url": url, "title": title, "text": text, "status_code": status, "error": None}

    except Exception as e:
        logger.warning(f"fetch_page('{url}') failed: {e}")
        return {"url": url, "title": "", "text": "", "status_code": 0, "error": str(e)}
