"""
Makima v2 — Web Page Fetcher and Search Tools.
Architectural Pattern: Library-first HTTP client with BeautifulSoup text sanitization and DuckDuckGo search extraction.
Zero-Hardcoding Guarantee: Fully dynamic URL normalization, realistic header synthesis, and zero-cost free endpoints.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any, Dict, List

import bs4
import httpx

from makima.core.http_pool import get_shared_client
from makima.tools.registry import tool

logger = logging.getLogger("makima.tools.browser.fetcher")

# Realistic browser headers for anti-bot tolerance without overriding automatic decompression
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _normalize_url(url: str) -> str:
    """Ensures URL contains scheme, defaulting to https://."""
    clean = url.strip()
    if not clean.startswith(("http://", "https://")):
        clean = f"https://{clean}"
    return clean


def _extract_text_from_html(html_content: str, max_length: int = 20000) -> tuple[str, str, bool]:
    """
    Parses HTML, removes script/style noise, extracts title and readable text.
    Returns: (title, clean_text, is_truncated)
    """
    soup = bs4.BeautifulSoup(html_content, "html.parser")

    # Extract title robustly
    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    # Decompose script, style, and decorative elements
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()

    # Extract clean text with newline separation
    text = soup.get_text(separator="\n", strip=True)

    # Collapse excessive consecutive newlines and whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    is_truncated = False
    if len(text) > max_length:
        text = text[:max_length] + "\n... [Content Truncated by Makima]"
        is_truncated = True

    return title, text, is_truncated


@tool(
    name="fetch_web_page",
    description=(
        "Use when you need to read the text content of a URL. "
        "Prefer web_search + fetch_page (from web_search tools) over this — "
        "they use a shared connection pool and are faster. "
        "Use this as a fallback when those are unavailable."
    ),
    tags=["web", "browser", "fetch"],
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
    target_url = _normalize_url(url)
    logger.info(f"Fetching web page: {target_url}")

    try:
        client = await get_shared_client()
        resp = await client.get(
            target_url,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=15.0,
        )

        final_url = str(resp.url)
        status_code = resp.status_code
        content_type = resp.headers.get("content-type", "")

        # Non-HTML content (e.g. plain text, json)
        if "text/html" not in content_type.lower():
            raw_text = resp.text
            truncated = len(raw_text) > max_length
            text_result = raw_text[:max_length] if truncated else raw_text
            return {
                "success": resp.is_success,
                "url": final_url,
                "status_code": status_code,
                "title": "",
                "text": text_result,
                "truncated": truncated,
                "length": len(text_result),
                "content_type": content_type,
            }

        # HTML parsing and extraction
        if extract_text:
            title, text, truncated = _extract_text_from_html(resp.text, max_length=max_length)
        else:
            title = ""
            title_tag = bs4.BeautifulSoup(resp.text, "html.parser").find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
            truncated = len(resp.text) > max_length
            text = resp.text[:max_length] if truncated else resp.text

        return {
            "success": resp.is_success,
            "url": final_url,
            "status_code": status_code,
            "title": title,
            "text": text,
            "truncated": truncated,
            "length": len(text),
            "content_type": content_type,
        }

    except httpx.TimeoutException:
        logger.warning(f"Timeout while fetching web page: {target_url}")
        return {
            "success": False,
            "url": target_url,
            "error": "Request timed out after 15 seconds.",
            "status_code": None,
        }
    except Exception as exc:
        logger.error(f"Error fetching web page {target_url}: {exc}")
        return {
            "success": False,
            "url": target_url,
            "error": f"{type(exc).__name__}: {str(exc)}",
            "status_code": None,
        }


def _unwrap_ddg_url(raw_url: str) -> str:
    """Extracts actual destination URL from DuckDuckGo redirect link."""
    if "uddg=" in raw_url:
        try:
            parsed = urllib.parse.urlparse(raw_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            if "uddg" in query_params:
                return query_params["uddg"][0]
        except Exception:
            pass
    return raw_url


@tool(
    name="search_web",
    description=(
        "Use when you need to search the web. "
        "Prefer web_search (from web_search tools) over this — it uses Tavily which "
        "gives better results. Use this only as a fallback when web_search is unavailable."
    ),
    tags=["web", "browser", "search"],
)
async def search_web(
    query: str,
    max_results: int = 5,
) -> Dict[str, Any]:
    """
    Executes a web search query without requiring paid API keys or tokens.

    Args:
        query: The search keywords or question.
        max_results: Maximum number of search results to return (1 to 20).

    Returns:
        Dictionary containing success flag, query, results list with title/snippet/url, and count.
    """
    clean_query = query.strip()
    if not clean_query:
        return {
            "success": False,
            "query": "",
            "results_count": 0,
            "results": [],
            "error": "Search query cannot be empty.",
        }

    limit = max(1, min(max_results, 20))
    logger.info(f"Performing web search: '{clean_query}' (limit={limit})")

    post_headers = {
        **DEFAULT_HEADERS,
        "Referer": "https://html.duckduckgo.com/",
        "Origin": "https://html.duckduckgo.com",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        client = await get_shared_client()
        resp = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": clean_query, "b": ""},
            headers=post_headers,
            follow_redirects=True,
            timeout=12.0,
        )

        if resp.status_code != 200:
            logger.warning(f"DuckDuckGo HTML returned HTTP {resp.status_code}")
            return {
                "success": False,
                "query": clean_query,
                "results_count": 0,
                "results": [],
                "error": f"Search provider returned status code {resp.status_code}",
            }

        soup = bs4.BeautifulSoup(resp.text, "html.parser")
        results: List[Dict[str, str]] = []

        for item in soup.select(".result"):
            # Exclude sponsored / ad results
            item_classes = item.get("class", [])
            if "result--ad" in item_classes:
                continue

            title_tag = item.select_one(".result__title a")
            snippet_tag = item.select_one(".result__snippet")

            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            raw_href = title_tag.get("href", "")
            target_url = _unwrap_ddg_url(raw_href)
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

            if target_url and title:
                results.append({
                    "title": title,
                    "url": target_url,
                    "snippet": snippet,
                })

            if len(results) >= limit:
                break

        return {
            "success": True,
            "query": clean_query,
            "results_count": len(results),
            "results": results,
            "error": None,
        }

    except httpx.TimeoutException:
        logger.warning(f"Timeout during web search for '{clean_query}'")
        return {
            "success": False,
            "query": clean_query,
            "results_count": 0,
            "results": [],
            "error": "Search request timed out after 12 seconds.",
        }
    except Exception as exc:
        logger.error(f"Error during web search for '{clean_query}': {exc}")
        return {
            "success": False,
            "query": clean_query,
            "results_count": 0,
            "results": [],
            "error": f"{type(exc).__name__}: {str(exc)}",
        }
