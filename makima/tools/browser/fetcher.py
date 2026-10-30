"""
Makima v2 — Web Page Fetcher and Search Tools.
Consolidated Web Search & Fetcher Facade delegating directly to canonical makima.tools.web_search.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from makima.tools.registry import tool
from makima.tools.web_search import (
    fetch_page as _canonical_fetch_page,
    web_search as _canonical_web_search,
)

logger = logging.getLogger("makima.tools.browser.fetcher")


@tool(
    name="fetch_web_page",
    description=(
        "Fetch and extract clean readable text from a URL. "
        "Consolidated with makima.tools.web_search.fetch_page."
    ),
    tags=["web", "browser", "fetch"],
    fallback_for="fetch_page",
)
async def fetch_web_page(
    url: str,
    extract_text: bool = True,
    max_length: int = 20000,
) -> Dict[str, Any]:
    """
    Fetches a web page over HTTP/HTTPS and extracts clean readable content.

    Args:
        url: The target web address to fetch.
        extract_text: If True, strips HTML/CSS/scripts and returns readable text.
        max_length: Maximum number of characters to return before truncation.

    Returns:
        Dictionary containing success status, url, status_code, title, text, and metadata.
    """
    if not url or not url.strip():
        return {
            "success": False,
            "url": url,
            "title": "",
            "text": "",
            "length": 0,
            "status_code": 0,
            "error": "URL cannot be empty.",
        }

    return await _canonical_fetch_page(
        url=url,
        extract_text=extract_text,
        max_length=max_length,
    )


@tool(
    name="search_web",
    description=(
        "Search the web using multi-source aggregator with heuristic quality filtering "
        "and summary synthesis. Consolidated with makima.tools.web_search.web_search."
    ),
    tags=["web", "browser", "search"],
    fallback_for="web_search",
)
async def search_web(
    query: str,
    max_results: int = 5,
) -> Any:
    """
    Executes a high-fidelity web search query with multi-provider aggregation.

    Args:
        query: The search keywords or question.
        max_results: Maximum number of search results to return (1 to 20).

    Returns:
        SearchResultList containing results with title/snippet/url, summary, and count.
    """
    clean_query = (query or "").strip()
    if not clean_query:
        from makima.tools.web_search import SearchResultList
        return SearchResultList(
            [],
            summary="",
            query="",
            sources=[],
            filtered_count=0,
            error="Search query cannot be empty.",
        )

    return await _canonical_web_search(query=clean_query, max_results=max_results)
