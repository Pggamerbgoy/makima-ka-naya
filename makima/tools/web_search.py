"""
Makima v2 — Ultra-High Quality Web Search, Research & Page Ingestion Engine.
Architectural Pattern: Multi-Source Search Aggregator with Heuristic Low-Quality Filtering & Summary Synthesis.

Features:
- Multi-Source Aggregator: Concurrently queries Tavily AI, DuckDuckGo HTML, DuckDuckGo Lite,
  DuckDuckGo Instant Answer API, Wikipedia REST API, and HackerNews Algolia API.
- Low-Quality Filter: Strips out Cloudflare/bot challenge pages, cookie/consent banners,
  paywall gates, dead error pages, empty/trivial fragments, and tracking parameters.
- Relevance & Authority Scoring: Ranks candidates by query token overlap, domain authority,
  and informational richness.
- Summary Synthesis Step: Synthesizes a factual, coherent overview answering the user query
  grounded in authoritative source citations.
- 100% Backwards Compatibility: Returns a SearchResultList (list subclass) supporting list iteration,
  attribute access (.summary, .query, .sources, .to_dict()), and dictionary serialization.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, quote, quote_plus, urlencode, urlparse, urlunparse
import webbrowser

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from tavily import AsyncTavilyClient
except ImportError:
    AsyncTavilyClient = None

from makima.core.http_pool import get_shared_client
from makima.tools.registry import tool

logger = logging.getLogger("makima.tools.web_search")

_DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Tracking query parameters to strip during canonicalization
_TRACKING_PARAMS: Set[str] = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "msclkid",
    "ref",
    "source",
    "ysclid",
    "_hsenc",
    "_hsmi",
    "mc_cid",
    "mc_eid",
    "spm",
    "igshid",
    "twclid",
    "sessionId",
}

# Patterns indicating bot-challenge, blocking, error, or paywall noise
_LOW_QUALITY_SNIPPET_PATTERNS = [
    re.compile(r"attention required|just a moment|cloudflare|ddos protection|ray id:", re.I),
    re.compile(r"enable javascript|verify you are human|robot or human|security check|captcha", re.I),
    re.compile(r"access denied|403 forbidden|404 not found|page not found|error 404", re.I),
    re.compile(r"accept all cookies|we use cookies|cookie preferences|cookie policy|consent preferences", re.I),
    re.compile(r"subscribe to read|sign in to your account|create a free account|you('ve| have) reached your free article limit", re.I),
    re.compile(r"please click here if you are not redirected|checking your browser", re.I),
]

_GENERIC_TITLES: Set[str] = {
    "home",
    "welcome",
    "index",
    "untitled",
    "404 not found",
    "page not found",
    "access denied",
    "error",
    "attention required! | cloudflare",
    "just a moment...",
}

# High-authority domains for scoring boost
_AUTHORITY_DOMAINS: Set[str] = {
    "wikipedia.org",
    "en.wikipedia.org",
    "github.com",
    "stackoverflow.com",
    "news.ycombinator.com",
    "docs.python.org",
    "developer.mozilla.org",
    "pypi.org",
    "w3.org",
    "ietf.org",
    "arxiv.org",
    "nature.com",
    "science.org",
    "reuters.com",
    "bloomberg.com",
    "bbc.com",
    "nytimes.com",
    "theverge.com",
    "kernel.org",
    "gnu.org",
    "apache.org",
}


class SearchResultList(list):
    """
    Enhanced list of search results.
    Acts as a standard List[Dict[str, Any]] for callers and tests,
    while also exposing .summary, .query, .sources, .filtered_count,
    dict-like key access (.get(), ['success'], ['results']), and a .to_dict() helper.
    """

    def __init__(
        self,
        items: List[Dict[str, Any]],
        summary: str = "",
        query: str = "",
        sources: Optional[List[str]] = None,
        filtered_count: int = 0,
        error: Optional[str] = None,
    ) -> None:
        super().__init__(items)
        self.summary = summary
        self.query = query
        self.sources = sources or []
        self.filtered_count = filtered_count
        self.error = error

    @property
    def results(self) -> List[Dict[str, Any]]:
        return list(self)

    @property
    def results_count(self) -> int:
        return len(self)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if item == "success":
                return bool(self.error is None and (len(self) > 0 or self.summary))
            if item == "error":
                return self.error
            if item == "results":
                return list(self)
            if item == "results_count":
                return len(self)
            if item == "summary":
                return self.summary
            if item == "query":
                return self.query
            if item == "sources":
                return self.sources
            if item == "filtered_count":
                return self.filtered_count
            if hasattr(self, item):
                return getattr(self, item)
            raise KeyError(item)
        return super().__getitem__(item)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except (KeyError, TypeError):
            return default

    def __contains__(self, item: Any) -> bool:
        if isinstance(item, str) and item in (
            "success", "error", "results", "results_count", "summary", "query", "sources", "filtered_count"
        ):
            return True
        return super().__contains__(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": bool(self.error is None and (len(self) > 0 or self.summary)),
            "error": self.error,
            "query": self.query,
            "summary": self.summary,
            "results_count": len(self),
            "filtered_count": self.filtered_count,
            "sources": self.sources,
            "results": list(self),
        }


def _get_tavily_api_key() -> Optional[str]:
    """Dynamically probes for Tavily API key from environment or user config."""
    key = os.getenv("TAVILY_API_KEY")
    if key and key.strip():
        return key.strip()

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
    """Unescapes HTML entities, strips tags if present, and normalizes excess whitespace."""
    if not text:
        return ""
    # Strip HTML tags via regex if any tag remains
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = html.unescape(clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _canonicalize_url(raw_url: str) -> str:
    """
    Normalizes a URL by un-wrapping search engine redirects (such as DDG uddg=),
    stripping marketing/tracking query parameters, removing fragments,
    and standardizing hostnames.
    """
    if not raw_url or not raw_url.strip():
        return ""

    url_str = raw_url.strip()

    # Unwrap DuckDuckGo uddg redirect
    if "uddg=" in url_str:
        try:
            parsed_redir = urlparse(url_str)
            uddg = parse_qs(parsed_redir.query).get("uddg", [""])[0]
            if uddg:
                url_str = uddg
        except Exception:
            pass

    try:
        parsed = urlparse(url_str)
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        path = parsed.path.rstrip("/")
        if not path:
            path = "/"

        # Filter out tracking query parameters
        qs = parse_qs(parsed.query, keep_blank_values=False)
        clean_qs = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        sorted_query = urlencode(clean_qs, doseq=True)

        return urlunparse((scheme, netloc, path, "", sorted_query, ""))
    except Exception:
        return url_str


def _extract_domain(url: str) -> str:
    """Extracts base domain from a URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def _is_low_quality(title: str, snippet: str, url: str) -> Tuple[bool, str]:
    """
    Heuristically checks if a candidate search result is low-quality,
    spam, bot challenge, or paywall boilerplate.
    Returns: (is_low_quality: bool, reason: str)
    """
    clean_t = (title or "").strip()
    clean_s = (snippet or "").strip()
    clean_u = (url or "").strip()

    if not clean_u or not clean_u.startswith(("http://", "https://")):
        return True, "Invalid or missing URL"

    if not clean_t or clean_t.lower() in _GENERIC_TITLES:
        return True, "Generic or empty title"

    # Reject known bot challenge / error titles
    if any(pattern.search(clean_t) for pattern in _LOW_QUALITY_SNIPPET_PATTERNS[:3]):
        return True, "Title indicates bot challenge or HTTP error"

    # Extremely short snippets without content
    if len(clean_s) < 20 and "wikipedia" not in clean_u:
        return True, "Snippet too short (<20 chars)"

    # Check for blocking / paywall / cookie patterns in snippet
    for pattern in _LOW_QUALITY_SNIPPET_PATTERNS:
        if pattern.search(clean_s):
            return True, f"Snippet matches junk pattern: {pattern.pattern[:30]}"

    # Check if snippet has almost no alphabetic words
    alpha_chars = sum(1 for c in clean_s if c.isalpha())
    if alpha_chars < 15 and "wikipedia" not in clean_u:
        return True, "Snippet contains insufficient alphabetic content"

    return False, ""


def _score_candidate(
    query_tokens: List[str],
    title: str,
    snippet: str,
    url: str,
    source: str,
) -> float:
    """
    Computes an objective quality and relevance score (0.0 to 1.0) for a search candidate.
    """
    score = 0.20  # Base score

    clean_t_lower = (title or "").lower()
    clean_s_lower = (snippet or "").lower()
    domain = _extract_domain(url)

    # 1. Query token matches in title (high signal)
    if query_tokens:
        matched_title = sum(1 for tok in query_tokens if tok in clean_t_lower)
        score += 0.35 * (matched_title / len(query_tokens))

        # Query token matches in snippet
        matched_snippet = sum(1 for tok in query_tokens if tok in clean_s_lower)
        score += 0.20 * (matched_snippet / len(query_tokens))

        # Exact phrase match bonus
        full_query = " ".join(query_tokens)
        if full_query in clean_t_lower:
            score += 0.15
        elif full_query in clean_s_lower:
            score += 0.08

    # 2. Domain Authority bonus
    if domain in _AUTHORITY_DOMAINS or any(domain.endswith(f".{ad}") for ad in _AUTHORITY_DOMAINS):
        score += 0.20
    elif domain.endswith(".edu") or domain.endswith(".gov") or domain.endswith(".org"):
        score += 0.12

    # 3. Source engine reliability bonus
    if source in ("wikipedia", "tavily"):
        score += 0.10
    elif source == "duckduckgo_instant":
        score += 0.08

    # 4. Snippet information quality & length
    s_len = len(snippet)
    if 100 <= s_len <= 450:
        score += 0.08  # Optimal informative length
    elif s_len < 60:
        score -= 0.08  # Too terse

    # Sentence structure bonus (ends with punctuation)
    if snippet and snippet[-1] in (".", "?", "!"):
        score += 0.04

    return max(0.0, min(1.0, round(score, 3)))


# -----------------------------------------------------------------------------
# Individual Search Sources
# -----------------------------------------------------------------------------


async def _search_tavily(
    query: str,
    limit: int,
    timelimit: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Source 1: Tavily AI Search (primary high-precision engine if API key present)."""
    tavily_key = _get_tavily_api_key()
    if not tavily_key or AsyncTavilyClient is None:
        return []

    try:
        time_range_map = {"d": "day", "w": "week", "m": "month", "y": "year"}
        time_range = time_range_map.get(timelimit) if timelimit in time_range_map else None

        tavily_client = AsyncTavilyClient(api_key=tavily_key)
        res = await asyncio.wait_for(
            tavily_client.search(
                query=query,
                max_results=limit,
                time_range=time_range,
            ),
            timeout=5.0,
        )

        candidates: List[Dict[str, Any]] = []
        for r in res.get("results", []):
            title = _clean_text(r.get("title", ""))
            url = str(r.get("url", "")).strip()
            snippet = _clean_text(r.get("content", ""))
            if title and url:
                candidates.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source": "tavily",
                })
        return candidates
    except Exception as exc:
        logger.debug("Tavily search skipped or failed: %s", exc)
        return []


async def _search_ddg_html(
    query: str,
    limit: int,
    timelimit: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Source 2: DuckDuckGo HTML Engine."""
    try:
        client = await get_shared_client()
        post_data = {"q": query, "b": "", "kl": "us-en"}
        if timelimit in ("d", "w", "m", "y"):
            post_data["df"] = timelimit

        resp = await client.post(
            "https://html.duckduckgo.com/html/",
            data=post_data,
            headers=_DESKTOP_HEADERS,
            follow_redirects=True,
            timeout=5.0,
        )

        if resp.status_code != 200:
            return []

        candidates: List[Dict[str, Any]] = []

        if BeautifulSoup:
            soup = BeautifulSoup(resp.text, "html.parser")
            for result_div in soup.select(".result__body"):
                title_tag = result_div.select_one(".result__title")
                snippet_tag = result_div.select_one(".result__snippet")
                if not title_tag:
                    continue

                title = _clean_text(title_tag.get_text())
                snippet = _clean_text(snippet_tag.get_text()) if snippet_tag else ""

                anchor = title_tag.select_one("a")
                href = anchor.get("href", "") if anchor else ""
                clean_url = _canonicalize_url(href)

                if clean_url and title:
                    candidates.append({
                        "title": title,
                        "url": clean_url,
                        "snippet": snippet,
                        "source": "duckduckgo_html",
                    })
                if len(candidates) >= limit:
                    break
        else:
            # Fallback regex extraction if BeautifulSoup is unavailable
            matches = re.findall(
                r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                resp.text,
                re.DOTALL,
            )
            for href, snippet_raw in matches[:limit]:
                clean_url = _canonicalize_url(href)
                candidates.append({
                    "title": query,
                    "url": clean_url,
                    "snippet": _clean_text(snippet_raw),
                    "source": "duckduckgo_html",
                })

        return candidates
    except Exception as exc:
        logger.debug("DuckDuckGo HTML search notice: %s", exc)
        return []


async def _search_ddg_lite(query: str, limit: int) -> List[Dict[str, Any]]:
    """Source 3: DuckDuckGo Lite Engine (ultra-fast, lightweight table format)."""
    try:
        client = await get_shared_client()
        post_data = {"q": query, "kl": "us-en"}
        resp = await client.post(
            "https://lite.duckduckgo.com/lite/",
            data=post_data,
            headers=_DESKTOP_HEADERS,
            follow_redirects=True,
            timeout=4.5,
        )

        if resp.status_code != 200:
            return []

        candidates: List[Dict[str, Any]] = []

        if BeautifulSoup:
            soup = BeautifulSoup(resp.text, "html.parser")
            # DuckDuckGo Lite displays results across consecutive table rows
            link_tags = soup.select("a.result-link")
            snippet_tags = soup.select("td.result-snippet")

            for idx, link_tag in enumerate(link_tags[:limit]):
                title = _clean_text(link_tag.get_text())
                href = link_tag.get("href", "")
                clean_url = _canonicalize_url(href)
                snippet = _clean_text(snippet_tags[idx].get_text()) if idx < len(snippet_tags) else ""

                if clean_url and title:
                    candidates.append({
                        "title": title,
                        "url": clean_url,
                        "snippet": snippet,
                        "source": "duckduckgo_lite",
                    })
        return candidates
    except Exception as exc:
        logger.debug("DuckDuckGo Lite search notice: %s", exc)
        return []


async def _fetch_ddg_instant_answer(query: str) -> Optional[Dict[str, Any]]:
    """Source 4: DuckDuckGo Instant Answer / Abstract API."""
    try:
        client = await get_shared_client()
        encoded = quote_plus(query.strip())
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1"
        resp = await client.get(url, headers=_DESKTOP_HEADERS, timeout=3.5)
        if resp.status_code == 200:
            data = resp.json()
            abstract = data.get("AbstractText", "").strip()
            heading = data.get("Heading", query).strip()
            source_url = data.get("AbstractURL", "").strip()
            if abstract:
                return {
                    "title": f"{heading} — Quick Overview",
                    "url": _canonicalize_url(source_url) or f"https://duckduckgo.com/?q={encoded}",
                    "snippet": _clean_text(abstract),
                    "source": "duckduckgo_instant",
                }
    except Exception as exc:
        logger.debug("DDG instant answer notice: %s", exc)
    return None


async def _fetch_wiki_summary(query: str) -> Optional[Dict[str, Any]]:
    """Source 5: Wikipedia REST Summary & OpenSearch API."""
    try:
        clean_q = re.sub(r"[^\w\s-]", "", query).strip()
        words = clean_q.split()
        if not words or len(words) > 8:
            return None

        client = await get_shared_client()

        # Step 1: Direct summary probe
        slug = quote(words[0].capitalize() if len(words) == 1 else "_".join(w.capitalize() for w in words[:3]))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
        resp = await client.get(url, headers={"User-Agent": "MakimaAssistant/2.0"}, timeout=3.5)

        if resp.status_code == 200:
            data = resp.json()
            title = data.get("title", "")
            extract = data.get("extract", "")
            page_url = data.get("content_urls", {}).get("desktop", {}).get("page", f"https://en.wikipedia.org/wiki/{slug}")
            if extract and len(extract) > 40:
                return {
                    "title": f"{title} (Wikipedia)",
                    "url": _canonicalize_url(page_url),
                    "snippet": _clean_text(extract),
                    "source": "wikipedia",
                }

        # Step 2: OpenSearch fallback for multi-word or non-exact slugs
        opensearch_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={quote_plus(clean_q)}&limit=1&namespace=0&format=json"
        os_resp = await client.get(opensearch_url, headers={"User-Agent": "MakimaAssistant/2.0"}, timeout=3.0)
        if os_resp.status_code == 200:
            os_data = os_resp.json()
            if len(os_data) >= 4 and os_data[1] and os_data[2] and os_data[3]:
                title = os_data[1][0]
                desc = os_data[2][0]
                page_url = os_data[3][0]
                if desc and len(desc) > 30:
                    return {
                        "title": f"{title} (Wikipedia)",
                        "url": _canonicalize_url(page_url),
                        "snippet": _clean_text(desc),
                        "source": "wikipedia",
                    }
    except Exception as exc:
        logger.debug("Wikipedia summary notice: %s", exc)
    return None


async def _search_bing(query: str, limit: int) -> List[Dict[str, Any]]:
    """Source: Direct Bing Search Engine (zero API key, resilient, fast)."""
    try:
        client = await get_shared_client()
        encoded = quote_plus(query.strip())
        url = f"https://www.bing.com/search?q={encoded}&setlang=en"
        resp = await client.get(url, headers=_DESKTOP_HEADERS, follow_redirects=True, timeout=3.5)
        if resp.status_code != 200:
            return []

        candidates: List[Dict[str, Any]] = []
        if BeautifulSoup:
            soup = BeautifulSoup(resp.text, "html.parser")
            for li in soup.select("li.b_algo"):
                h2 = li.select_one("h2 a")
                if not h2:
                    continue
                title = _clean_text(h2.get_text())
                href = h2.get("href", "")

                cite_tag = li.select_one("cite")
                if cite_tag:
                    cite_text = _clean_text(cite_tag.get_text())
                    if cite_text.startswith("http"):
                        cite_url = cite_text.split(" › ")[0].split(" ")[0].strip()
                        if "." in cite_url and not cite_url.endswith("."):
                            href = cite_url

                p_tag = li.select_one("p") or li.select_one(".b_caption")
                snippet = _clean_text(p_tag.get_text()) if p_tag else ""
                clean_url = _canonicalize_url(href)

                if clean_url and title:
                    candidates.append({
                        "title": title,
                        "url": clean_url,
                        "snippet": snippet,
                        "source": "bing",
                    })
                if len(candidates) >= limit:
                    break
        else:
            items = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', resp.text, re.DOTALL)
            for it in items[:limit]:
                h2 = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></h2>', it)
                p = re.search(r'<p[^>]*>(.*?)</p>', it)
                cite = re.search(r'<cite[^>]*>(.*?)</cite>', it)
                if h2:
                    title = _clean_text(h2.group(2))
                    href = h2.group(1)
                    if cite:
                        cite_text = _clean_text(cite.group(1))
                        if cite_text.startswith("http"):
                            c_part = cite_text.split(" › ")[0].split(" ")[0].strip()
                            if "." in c_part:
                                href = c_part
                    snippet = _clean_text(p.group(1)) if p else ""
                    clean_url = _canonicalize_url(href)
                    if clean_url and title:
                        candidates.append({
                            "title": title,
                            "url": clean_url,
                            "snippet": snippet,
                            "source": "bing",
                        })
        return candidates
    except Exception as exc:
        logger.debug("Bing search notice: %s", exc)
        return []


async def _search_hackernews(query: str, limit: int) -> List[Dict[str, Any]]:
    """Source 6: Hacker News Algolia Search (rich developer, tech, and engineering intelligence)."""
    try:
        # Only query Hacker News for tech/code/system/engineering queries
        tech_indicators = {
            "python", "javascript", "rust", "go", "code", "ai", "llm", "api", "framework",
            "database", "linux", "git", "benchmark", "release", "library", "react", "fastapi",
        }
        words = set(re.findall(r"\w+", query.lower()))
        if not (words & tech_indicators) and len(words) > 3:
            return []

        client = await get_shared_client()
        encoded = quote_plus(query.strip())
        url = f"https://hn.algolia.com/api/v1/search?query={encoded}&tags=story&hitsPerPage={min(limit, 4)}"
        resp = await client.get(url, timeout=3.5)

        if resp.status_code != 200:
            return []

        data = resp.json()
        candidates: List[Dict[str, Any]] = []
        for hit in data.get("hits", []):
            title = _clean_text(hit.get("title", ""))
            story_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            clean_url = _canonicalize_url(story_url)
            points = hit.get("points", 0)
            num_comments = hit.get("num_comments", 0)

            snippet = f"Hacker News community discussion ({points} points, {num_comments} comments) on {title}."
            if clean_url and title:
                candidates.append({
                    "title": f"{title} — Hacker News",
                    "url": clean_url,
                    "snippet": snippet,
                    "source": "hackernews",
                })
        return candidates
    except Exception as exc:
        logger.debug("Hacker News search notice: %s", exc)
        return []


async def _enrich_snippet_from_url(url: str, current_snippet: str) -> str:
    """Enriches a short snippet by fetching the introductory body paragraph of the destination page."""
    if len(current_snippet) >= 160 or not url.startswith("http"):
        return current_snippet

    try:
        client = await get_shared_client()
        resp = await client.get(url, headers=_DESKTOP_HEADERS, follow_redirects=True, timeout=2.5)
        if resp.status_code == 200 and "html" in resp.headers.get("content-type", ""):
            if BeautifulSoup:
                soup = BeautifulSoup(resp.text[:50000], "html.parser")
                for noise in soup(["script", "style", "nav", "header", "footer", "aside"]):
                    noise.decompose()
                p = soup.find("p")
                if p:
                    text = _clean_text(p.get_text())
                    if len(text) > len(current_snippet) + 20:
                        return text[:380]
            else:
                p_match = re.search(r"<p[^>]*>(.*?)</p>", resp.text[:50000], re.DOTALL | re.IGNORECASE)
                if p_match:
                    text = _clean_text(p_match.group(1))
                    if len(text) > len(current_snippet) + 20:
                        return text[:380]
    except Exception:
        pass

    return current_snippet


# -----------------------------------------------------------------------------
# Summary Synthesis Step
# -----------------------------------------------------------------------------


def _synthesize_search_summary(
    query: str,
    candidates: List[Dict[str, Any]],
) -> str:
    """
    Synthesizes a clean, authoritative executive summary from the top filtered results.
    Consolidates factual definitions and key findings with domain source citations.
    """
    if not candidates:
        return f"No authoritative web results could be synthesized for '{query}'."

    # Look for primary authoritative definition
    primary_definition = ""
    for c in candidates:
        if c.get("source") in ("wikipedia", "duckduckgo_instant"):
            primary_definition = c.get("snippet", "")
            break

    # Gather high-signal factual sentences from top distinct sources
    sentences: List[str] = []
    seen_domains: Set[str] = set()
    source_names: List[str] = []

    for c in candidates[:4]:
        domain = _extract_domain(c.get("url", ""))
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            source_names.append(domain)

        snippet = c.get("snippet", "")
        if not snippet:
            continue

        # Split snippet into sentences
        parts = re.split(r"(?<=[.!?])\s+", snippet)
        for p in parts:
            clean_p = _clean_text(p)
            if len(clean_p) > 30 and not any(clean_p.lower() in s.lower() for s in sentences):
                sentences.append(clean_p)
            if len(sentences) >= 4:
                break
        if len(sentences) >= 4:
            break

    # Build coherent synthesized narrative
    summary_parts = []
    if primary_definition:
        summary_parts.append(primary_definition)
    elif sentences:
        summary_parts.append(" ".join(sentences[:2]))

    # Add secondary points if distinct
    remaining_sentences = [s for s in sentences if s not in summary_parts]
    if remaining_sentences:
        summary_parts.append(" ".join(remaining_sentences[:2]))

    compiled_summary = "\n\n".join(summary_parts) if summary_parts else candidates[0].get("snippet", "")

    # Append source domain citations if available
    if source_names:
        citations = ", ".join(source_names[:3])
        compiled_summary += f" (Sources: {citations})"

    return compiled_summary


# -----------------------------------------------------------------------------
# Public Web Search & Ingestion Tools
# -----------------------------------------------------------------------------


@tool(
    name="web_search",
    description=(
        "Search the live web using a multi-source aggregator (Tavily, DuckDuckGo, Wikipedia, "
        "HackerNews) with automated low-quality result filtering and summary synthesis. "
        "Returns high-signal, deduplicated results with an executive summary and verified citations."
    ),
    tags=["web", "search", "internet", "research", "synthesis"],
)
async def web_search(
    query: str,
    max_results: int = 5,
    timelimit: Optional[str] = None,
    return_dict: bool = False,
) -> Any:
    """
    Search the web with multi-source aggregation, heuristic filtering, and summary synthesis.

    Args:
        query: Search keywords or user question.
        max_results: Maximum results to return (1 to 10).
        timelimit: Optional filter: 'd' (day), 'w' (week), 'm' (month), 'y' (year).
        return_dict: If True, returns dict format with summary; if False, returns SearchResultList.

    Returns:
        SearchResultList (behaves as List[Dict[str, Any]] with .summary attribute and .to_dict() method).
    """
    if not query or not query.strip():
        empty_list = SearchResultList(
            [],
            summary="",
            query="",
            sources=[],
            filtered_count=0,
            error="Search query cannot be empty.",
        )
        return empty_list.to_dict() if return_dict else empty_list

    clean_q = query.strip()
    limit = max(1, min(10, max_results))

    # Tokenize query for scoring
    raw_tokens = re.findall(r"\w+", clean_q.lower())
    stop_words = {"the", "a", "an", "is", "of", "and", "or", "in", "to", "for", "with", "on", "at", "by", "what", "how"}
    query_tokens = [t for t in raw_tokens if t not in stop_words] or raw_tokens

    # -------------------------------------------------------------------------
    # 1. Multi-Source Concurrent Gathering
    # -------------------------------------------------------------------------
    tasks = [
        _search_tavily(clean_q, limit=limit, timelimit=timelimit),
        _search_bing(clean_q, limit=limit),
        _search_ddg_html(clean_q, limit=limit + 2, timelimit=timelimit),
        _search_ddg_lite(clean_q, limit=limit + 2),
        _fetch_ddg_instant_answer(clean_q),
        _fetch_wiki_summary(clean_q),
        _search_hackernews(clean_q, limit=limit),
    ]

    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    raw_candidates: List[Dict[str, Any]] = []
    sources_queried: List[str] = []

    for idx, item in enumerate(gathered):
        if isinstance(item, Exception):
            logger.debug("Source task %d failed: %s", idx, item)
            continue
        if isinstance(item, list):
            raw_candidates.extend(item)
        elif isinstance(item, dict) and item.get("title") and item.get("url"):
            raw_candidates.append(item)

    # -------------------------------------------------------------------------
    # 2. Heuristic Low-Quality Filtering & Canonical Deduplication
    # -------------------------------------------------------------------------
    filtered_candidates: List[Dict[str, Any]] = []
    seen_canonical_urls: Set[str] = set()
    filtered_out_count = 0

    for candidate in raw_candidates:
        title = candidate.get("title", "")
        snippet = candidate.get("snippet", "")
        raw_url = candidate.get("url", "")
        source = candidate.get("source", "unknown")

        canonical_url = _canonicalize_url(raw_url)
        if not canonical_url:
            filtered_out_count += 1
            continue

        # Deduplication check
        if canonical_url in seen_canonical_urls:
            # If we've seen this URL, keep the version with the longer snippet
            for existing in filtered_candidates:
                if existing["url"] == canonical_url:
                    if len(snippet) > len(existing.get("snippet", "")):
                        existing["snippet"] = snippet
                        existing["title"] = title
                    break
            continue

        # Check for low-quality, captcha, paywall, or broken snippet
        is_bad, reason = _is_low_quality(title=title, snippet=snippet, url=canonical_url)
        if is_bad:
            logger.debug("Filtered out low-quality result '%s' (%s): %s", title[:30], canonical_url[:40], reason)
            filtered_out_count += 1
            continue

        seen_canonical_urls.add(canonical_url)

        # Calculate quality & relevance score
        score = _score_candidate(
            query_tokens=query_tokens,
            title=title,
            snippet=snippet,
            url=canonical_url,
            source=source,
        )

        filtered_candidates.append({
            "title": title,
            "url": canonical_url,
            "snippet": snippet,
            "source": source,
            "score": score,
        })
        if source not in sources_queried:
            sources_queried.append(source)

    # -------------------------------------------------------------------------
    # 3. Sort by Quality Score & Enrich Top Results
    # -------------------------------------------------------------------------
    filtered_candidates.sort(key=lambda x: x["score"], reverse=True)
    selected_results = filtered_candidates[:limit]

    # Snippet Enrichment: live paragraph fetch for top candidates with short snippets
    if selected_results:
        enrich_tasks = []
        for cand in selected_results[:2]:
            enrich_tasks.append(_enrich_snippet_from_url(cand["url"], cand["snippet"]))
        enriched_texts = await asyncio.gather(*enrich_tasks, return_exceptions=True)
        for idx, en_val in enumerate(enriched_texts):
            if isinstance(en_val, str) and len(en_val) > len(selected_results[idx]["snippet"]):
                selected_results[idx]["snippet"] = en_val

    # -------------------------------------------------------------------------
    # 4. Summary Synthesis Step
    # -------------------------------------------------------------------------
    synthesis_summary = _synthesize_search_summary(clean_q, selected_results)

    # Attach synthesis summary to each result item for convenience
    for res_item in selected_results:
        res_item["summary"] = synthesis_summary

    # Wrap in SearchResultList
    result_container = SearchResultList(
        items=selected_results,
        summary=synthesis_summary,
        query=clean_q,
        sources=sources_queried,
        filtered_count=filtered_out_count,
    )

    logger.debug(
        "web_search('%s') -> %d results (sources=%s, filtered=%d)",
        clean_q,
        len(selected_results),
        sources_queried,
        filtered_out_count,
    )

    if return_dict:
        return result_container.to_dict()

    return result_container


@tool(
    name="fetch_page",
    description=(
        "Fetch and extract readable article text from any URL. Strips out ads, cookie banners, "
        "and layout navigation, returning clean text and Markdown content."
    ),
    tags=["web", "fetch", "read", "scrape"],
)
async def fetch_page(
    url: str,
    extract_text: bool = True,
    max_chars: int = 12000,
    max_length: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fetches a URL and extracts readable text content using shared connection pool.

    Args:
        url: The web page URL to fetch.
        extract_text: If True, extracts sanitized readable body text; if False, returns raw HTML.
        max_chars: Maximum characters to return (defaults to 12,000).
        max_length: Optional alias for max_chars (defaults to None).

    Returns:
        Dict containing success, url, title, text, length, status_code, and error.
    """
    char_limit = max_length if max_length is not None else max_chars

    if not url or not url.strip():
        return {
            "success": False,
            "url": url,
            "title": "",
            "text": "",
            "length": 0,
            "status_code": 0,
            "error": "Empty URL",
        }

    target_url = url.strip()
    if not target_url.startswith(("http://", "https://")):
        target_url = "https://" + target_url

    client = await get_shared_client()

    try:
        resp = await client.get(target_url, headers=_DESKTOP_HEADERS, follow_redirects=True, timeout=12.0)
        status = resp.status_code

        if status >= 400:
            return {
                "success": False,
                "url": target_url,
                "title": "",
                "text": "",
                "length": 0,
                "status_code": status,
                "error": f"HTTP {status}",
            }

        content_type = resp.headers.get("content-type", "").lower()
        if "html" not in content_type and "text" not in content_type:
            raw_desc = f"[Non-text binary content: {content_type}]"
            return {
                "success": True,
                "url": target_url,
                "title": "",
                "text": raw_desc,
                "length": len(raw_desc),
                "status_code": status,
                "error": None,
            }

        title = ""
        clean_result = ""

        if BeautifulSoup:
            soup = BeautifulSoup(resp.text, "html.parser")
            title_tag = soup.find("title")
            title = _clean_text(title_tag.get_text()) if title_tag else ""

            if not extract_text:
                raw_text = resp.text[:char_limit]
                return {
                    "success": True,
                    "url": target_url,
                    "title": title,
                    "text": raw_text,
                    "length": len(raw_text),
                    "status_code": status,
                    "error": None,
                }

            # Remove clutter tags
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "svg", "noscript", "iframe"]):
                tag.decompose()

            # Prioritize main article container
            main = (
                soup.find("article")
                or soup.find("main")
                or soup.find(id=re.compile(r"content|article|main", re.I))
                or soup.find(class_=re.compile(r"post|article|content", re.I))
                or soup.body
            )
            text = main.get_text(separator="\n") if main else soup.get_text(separator="\n")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            clean_result = "\n".join(lines)
        else:
            # Fallback regex extraction if BeautifulSoup is not installed
            title_match = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.IGNORECASE | re.DOTALL)
            title = _clean_text(title_match.group(1)) if title_match else ""

            if not extract_text:
                raw_text = resp.text[:char_limit]
                return {
                    "success": True,
                    "url": target_url,
                    "title": title,
                    "text": raw_text,
                    "length": len(raw_text),
                    "status_code": status,
                    "error": None,
                }

            text = re.sub(r"<(script|style|nav|footer|header|aside|noscript|iframe)[^>]*>.*?</\1>", " ", resp.text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = html.unescape(text)
            lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
            clean_result = "\n".join(lines)

        truncated = len(clean_result) > char_limit
        if truncated:
            clean_result = clean_result[:char_limit] + f"\n\n[... truncated at {char_limit} chars]"

        return {
            "success": True,
            "url": str(resp.url),
            "title": title,
            "text": clean_result,
            "length": len(clean_result),
            "truncated": truncated,
            "status_code": status,
            "error": None,
        }
    except Exception as exc:
        logger.warning("fetch_page('%s') failed: %s", target_url, exc)
        return {
            "success": False,
            "url": target_url,
            "title": "",
            "text": "",
            "length": 0,
            "status_code": 0,
            "error": str(exc),
        }


@tool(
    name="deep_web_research",
    description=(
        "Conduct thorough multi-source web research on a complex topic. "
        "Searches the web, visits top authoritative pages in parallel, extracts key evidence, "
        "and synthesizes a comprehensive research dossier with source citations."
    ),
    tags=["web", "research", "deep_research", "synthesis"],
)
async def deep_web_research(
    topic: str,
    max_sources: int = 3,
) -> Dict[str, Any]:
    """
    Executes automated deep research across multiple live web pages.

    Args:
        topic: The research query or technical question to investigate.
        max_sources: Number of distinct web pages to scrape and synthesize (2 to 5).

    Returns:
        Structured research report with summary, key findings, and source references.
    """
    clean_topic = topic.strip()
    limit = max(2, min(5, max_sources))

    # Step 1: Run search to locate top sources
    search_hits = await web_search(clean_q := clean_topic, max_results=limit + 2)
    if not search_hits:
        return {
            "topic": clean_topic,
            "sources_analyzed": 0,
            "findings": "No reliable web sources could be found for this topic.",
            "sources": [],
        }

    # Step 2: Fetch the actual articles in parallel
    fetch_tasks = [fetch_page(hit["url"], max_chars=4000) for hit in search_hits[:limit]]
    pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)

    dossier: List[Dict[str, Any]] = []
    for idx, page in enumerate(pages):
        if isinstance(page, dict) and page.get("text") and not page.get("error"):
            hit = search_hits[idx]
            dossier.append({
                "title": page.get("title") or hit.get("title"),
                "url": page.get("url"),
                "content_preview": page.get("text")[:1500],
            })

    return {
        "topic": clean_topic,
        "summary": getattr(search_hits, "summary", "") or (search_hits[0].get("summary", "") if search_hits else ""),
        "sources_analyzed": len(dossier),
        "sources": dossier,
    }


@tool(
    name="search_in_native_browser",
    description=(
        "Opens the user's real desktop browser (Chrome, Edge, Brave, etc.) directly with a Google or Bing search query. "
        "Use whenever the user wants to see live search results on their PC screen or when scrapers are blocked."
    ),
    tags=["web", "browser", "desktop", "native", "google"],
)
async def search_in_native_browser(
    query: str,
    engine: str = "google",
) -> Dict[str, Any]:
    """
    Launches the host PC's native default browser directly with a search query.

    Args:
        query: Search keywords or question.
        engine: 'google' (default) or 'bing'.

    Returns:
        Dict indicating launch status and opened URL.
    """
    clean_q = query.strip()
    encoded = quote_plus(clean_q)
    engine_lower = engine.strip().lower()

    if engine_lower == "bing":
        url = f"https://www.bing.com/search?q={encoded}"
    else:
        url = f"https://www.google.com/search?q={encoded}"

    try:
        opened = webbrowser.open(url)
        return {
            "success": True,
            "engine": engine_lower,
            "query": clean_q,
            "url": url,
            "opened_in_native_browser": opened,
            "message": f"Opened {engine_lower.capitalize()} search for '{clean_q}' in native desktop browser.",
        }
    except Exception as exc:
        return {
            "success": False,
            "engine": engine_lower,
            "query": clean_q,
            "url": url,
            "error": str(exc),
        }

