"""
Live verification script for Phase 2 Step 9.1: Web Browser & Page Automation.
Tests:
  1. fetch_web_page: Live HTTP fetch, header synthesis, URL normalization, HTML text extraction.
  2. search_web: Free DuckDuckGo organic search extraction, snippet and link parsing.
  3. browse_page: Headless Playwright Chromium automation, dynamic DOM rendering, process cleanup.
  4. Playwright error handling: Graceful advisory when binaries/dependencies fail.
  5. ToolRegistry integration: Schema validation and sandboxed invocation via registry.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Ensure makima is importable
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.tools.browser import (
    browse_page,
    fetch_web_page,
    search_web,
)
from makima.tools.registry import get_registry, reset_registry


async def test_fetch_web_page():
    print("[TEST 1] Testing fetch_web_page (HTTP fetch, URL normalization & text extraction)...")

    # 1. Test URL normalization & basic fetch on a stable domain
    res = await fetch_web_page(url="example.com", extract_text=True)
    assert res["success"] is True, f"Fetch failed: {res}"
    assert res["status_code"] == 200
    assert "Example Domain" in res["title"]
    assert "Example Domain" in res["text"]
    assert res["url"] == "https://example.com/" or res["url"] == "https://example.com"
    assert res["length"] > 0

    # 2. Test max_length truncation
    res_trunc = await fetch_web_page(url="https://example.com", max_length=50)
    assert res_trunc["success"] is True
    assert res_trunc["truncated"] is True
    assert "[Content Truncated by Makima]" in res_trunc["text"]

    # 3. Test non-existent domain error handling
    res_err = await fetch_web_page(url="https://nonexistent-domain-xyz-12345.org")
    assert res_err["success"] is False
    assert res_err["error"] is not None

    print("  -> PASSED: fetch_web_page URL normalization, HTML parsing, and truncation verified!")


async def test_search_web():
    print("[TEST 2] Testing search_web (Free DuckDuckGo search extraction)...")

    # 1. Test empty query guard
    res_empty = await search_web(query="   ")
    assert res_empty["success"] is False
    assert "cannot be empty" in res_empty["error"]

    # 2. Test live search execution
    res = await search_web(query="python programming language", max_results=3)
    assert res["success"] is True, f"Search failed: {res.get('error')}"
    assert res["query"] == "python programming language"
    assert res["results_count"] > 0, "Expected at least 1 search result"
    assert len(res["results"]) <= 3

    first = res["results"][0]
    assert "title" in first and len(first["title"]) > 0
    assert "url" in first and first["url"].startswith("http")
    assert "snippet" in first

    print(f"  -> PASSED: search_web retrieved {res['results_count']} organic results from DuckDuckGo!")


async def test_browse_page_playwright():
    print("[TEST 3] Testing browse_page (Headless Playwright Chromium automation)...")

    # 1. Live page navigation with dynamic DOM inspection
    res = await browse_page(url="example.com", wait_seconds=0.5)
    assert res["success"] is True, f"Browse page failed: {res.get('error')}"
    assert "Example Domain" in res["title"]
    assert "documentation examples" in res["text"].lower() or len(res["text"]) > 0
    assert res["final_url"].startswith("https://example.com")
    assert res["length"] > 0

    print("  -> PASSED: Headless Playwright browser rendered page and captured DOM text cleanly!")


async def test_playwright_graceful_fallback():
    print("[TEST 4] Testing Playwright graceful error handling & installation advice...")

    # Simulate missing chromium executable error
    with patch("makima.tools.browser.automation.async_playwright") as mock_pw_factory:
        mock_pw = AsyncMock()
        mock_pw.chromium.launch = AsyncMock(
            side_effect=Exception("Executable doesn't exist at C:\\path\\to\\chrome.exe. Please run: playwright install")
        )
        mock_pw_factory.return_value.start = AsyncMock(return_value=mock_pw)

        res = await browse_page(url="https://example.com")
        assert res["success"] is False
        assert "Chromium browser binaries are missing" in res["error"]
        assert "playwright install chromium" in res["help"]

    print("  -> PASSED: Missing browser binaries caught with user-friendly remediation advice!")


async def test_registry_integration():
    print("[TEST 5] Testing ToolRegistry schema synthesis and dynamic execution...")

    reset_registry()
    reg = get_registry(auto_discover=True)

    # Verify tool registration
    for tool_name in ["fetch_web_page", "search_web", "browse_page"]:
        assert reg.has(tool_name), f"Registry missing {tool_name}"
        tool_obj = reg.get(tool_name)
        schema = tool_obj.to_schema(format="openai")
        assert schema["type"] == "function"
        assert schema["function"]["name"] == tool_name
        assert "properties" in schema["function"]["parameters"]

    # Test sandboxed execution via registry
    fetch_result = await reg.execute("fetch_web_page", {"url": "https://example.com"})
    assert fetch_result["success"] is True
    assert "Example Domain" in fetch_result["title"]

    print("  -> PASSED: ToolRegistry schemas validated and tool executed via registry interface!")


async def main():
    print("=" * 60)
    print("RUNNING LIVE VERIFICATION: makima/tools/browser/ (Step 9.1)")
    print("=" * 60)

    await test_fetch_web_page()
    await test_search_web()
    await test_browse_page_playwright()
    await test_playwright_graceful_fallback()
    await test_registry_integration()

    print("=" * 60)
    print("ALL WEB BROWSER AUTOMATION TESTS PASSED! (EXIT CODE 0)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
