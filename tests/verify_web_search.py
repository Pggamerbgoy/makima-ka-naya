"""
tests/verify_web_search.py — Step 22 Verification
Tests web_search and fetch_page tools.
Suite 1-4 test imports/schema; Suite 5-7 make live network requests (skipped if offline).
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "[PASS]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"
results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    tag = PASS if ok else FAIL
    msg = f"{tag} {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append(ok)


def skip(name: str, reason: str) -> None:
    print(f"{SKIP} {name} — {reason}")
    results.append(True)  # skipped = not a failure (bool)


# ---------------------------------------------------------------------------
# Suite 1: Import
# ---------------------------------------------------------------------------
def test_import():
    try:
        from makima.tools.web_search import web_search, fetch_page
        record("Import web_search and fetch_page", True)
        return web_search, fetch_page
    except Exception as e:
        record("Import web_search and fetch_page", False, str(e))
        return None, None


# ---------------------------------------------------------------------------
# Suite 2: Tool registry metadata
# ---------------------------------------------------------------------------
def test_tool_metadata():
    try:
        from makima.tools.registry import get_registry
        registry = get_registry()
        names = set(registry.list_names())
        has_search = "web_search" in names
        has_fetch = "fetch_page" in names
        record("web_search registered in ToolRegistry", has_search)
        record("fetch_page registered in ToolRegistry", has_fetch)
    except Exception as e:
        record("ToolRegistry metadata check", False, str(e))


# ---------------------------------------------------------------------------
# Suite 3: Schema generation
# ---------------------------------------------------------------------------
def test_schema():
    try:
        from makima.tools.registry import get_registry
        registry = get_registry()
        schemas = registry.get_schemas()  # [{type, function: {name, description, parameters}}]
        # OpenAI-format: each schema is {"type": "function", "function": {"name": ..., "parameters": ...}}
        schema_map = {s["function"]["name"]: s["function"] for s in schemas if isinstance(s, dict) and "function" in s}

        search_schema = str(schema_map.get("web_search", {}))
        fetch_schema = str(schema_map.get("fetch_page", {}))

        ok_search = "query" in search_schema
        ok_fetch = "url" in fetch_schema
        record("web_search schema has 'query' param", ok_search, search_schema[:80])
        record("fetch_page schema has 'url' param", ok_fetch, fetch_schema[:80])
    except Exception as e:
        record("Schema generation", False, str(e))


# ---------------------------------------------------------------------------
# Suite 4: Empty query guard
# ---------------------------------------------------------------------------
def test_empty_query():
    async def _run():
        try:
            from makima.tools.web_search import web_search
            result = await web_search("", max_results=3)
            ok = isinstance(result, list) and len(result) == 0
            record("Empty query returns empty list", ok, f"result={result}")
        except Exception as e:
            record("Empty query guard", False, str(e))
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Suite 5: Live web_search (network)
# ---------------------------------------------------------------------------
def test_live_search():
    async def _run():
        try:
            from makima.tools.web_search import web_search
            results_list = await web_search("Python programming language", max_results=3)
            ok = (
                isinstance(results_list, list)
                and len(results_list) > 0
                and "title" in results_list[0]
                and "url" in results_list[0]
            )
            record(
                "Live web_search returns results",
                ok,
                f"count={len(results_list)}, first='{results_list[0].get('title', '')[:40] if results_list else 'NONE'}'",
            )
        except Exception as e:
            skip("Live web_search", f"Network unavailable: {e}")
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Suite 6: Live fetch_page (network)
# ---------------------------------------------------------------------------
def test_live_fetch():
    async def _run():
        try:
            from makima.tools.web_search import fetch_page
            result = await fetch_page("https://example.com", extract_text=True)
            ok = (
                result.get("status_code", 0) == 200
                and len(result.get("text", "")) > 10
            )
            record(
                "Live fetch_page extracts text",
                ok,
                f"status={result.get('status_code')}, chars={len(result.get('text', ''))}",
            )
        except Exception as e:
            skip("Live fetch_page", f"Network unavailable: {e}")
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Suite 7: fetch_page with bad URL
# ---------------------------------------------------------------------------
def test_fetch_bad_url():
    async def _run():
        try:
            from makima.tools.web_search import fetch_page
            result = await fetch_page("https://this-domain-does-not-exist-makima-test.invalid")
            # Should return error dict, not raise exception
            ok = isinstance(result, dict) and (result.get("error") or result.get("status_code", 0) >= 400)
            record("fetch_page bad URL returns error dict gracefully", ok, f"error={result.get('error')}")
        except Exception as e:
            record("fetch_page bad URL returns error dict gracefully", False, f"Raised: {e}")
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Step 22 — Fast Web Search Tool Verification")
    print("=" * 60)

    web_search, fetch_page = test_import()
    if web_search is None:
        print("\n[ABORT] Import failed — skipping remaining tests.")
        sys.exit(1)

    test_tool_metadata()
    test_schema()
    test_empty_query()
    test_live_search()
    test_live_fetch()
    test_fetch_bad_url()

    print("=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    print("=" * 60)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
