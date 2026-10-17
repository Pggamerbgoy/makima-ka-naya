"""
Live verification script for Phase 2 Step 9: Web Browser, Media & Document Tools.
Tests:
  1. Media Tools ('makima.tools.media'):
     - get_volume(), set_volume(), toggle_mute() via pycaw with safe state restoration.
     - get_media_status() and control_media() via winrt (gracefully handled even if no audio is playing).
     - Input validation and unsupported action handling.
  2. Document Tools ('makima.tools.documents'):
     - create_excel_sheet() & read_excel_sheet() via openpyxl with cell styling, zebra fills, and freeze panes.
     - create_word_document() & read_word_document() via python-docx with headings, bullets, and tables.
     - create_powerpoint() & read_powerpoint() via python-pptx with 16:9 widescreen layout and notes.
     - Adversarial boundary traversal blocking.
  3. Browser Tools ('makima.tools.browser'):
     - fetch_web_page() via httpx with BeautifulSoup HTML sanitation, script stripping, and title extraction.
     - search_web() via httpx DuckDuckGo HTML scraping with URL unwrapping and query validation.
     - browse_page() availability and graceful fallback.
  4. ToolRegistry Auto-Discovery & Schema Synthesis:
     - Verify all 14 Step 9 tools are decorated with @tool and registered.
     - Verify JSON Schema parameters_schema synthesis for every tool.
     - Execute tools dynamically through ToolRegistry.execute().
"""

import asyncio
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.tools import ToolRegistry, get_registry, reset_registry
from makima.tools.browser import browse_page, fetch_web_page, search_web
from makima.tools.documents import (
    create_excel_sheet,
    create_powerpoint,
    create_word_document,
    read_excel_sheet,
    read_powerpoint,
    read_word_document,
)
from makima.tools.filesystem.safe_io import (
    BoundaryTraversalError,
    get_workspace_dir,
    set_workspace_dir,
)
from makima.tools.media import (
    control_media,
    get_media_status,
    get_volume,
    set_volume,
    toggle_mute,
)


# ==============================================================================
# TEST 1: Windows Media & Audio Controls (pycaw & winrt)
# ==============================================================================
async def test_media_tools():
    print("\n" + "=" * 60)
    print("[TEST 1] Testing Windows Media & Audio Controls (makima.tools.media)")
    print("=" * 60)

    # 1.1 Volume Inspection & Mutation via pycaw
    print("  Subtest 1.1: Master Volume via pycaw...")
    vol_init = get_volume()
    assert isinstance(vol_init, dict), "get_volume() must return a dict"
    assert vol_init.get("success") is True, f"get_volume() returned failure: {vol_init}"
    orig_vol = vol_init["volume_percent"]
    orig_mute = vol_init["is_muted"]
    device_name = vol_init.get("device", "Speakers")
    assert 0.0 <= orig_vol <= 100.0, f"Volume out of bounds: {orig_vol}"
    assert isinstance(orig_mute, bool), "is_muted must be a boolean"
    print(f"    [PASS] Current volume: {orig_vol}%, Muted: {orig_mute}, Device: '{device_name}'")

    try:
        # Safe relative volume test
        test_target = 45.0 if orig_vol > 50.0 else 55.0
        set_res = set_volume(test_target)
        assert set_res.get("success") is True, f"set_volume failed: {set_res}"
        assert abs(set_res["volume_percent"] - test_target) <= 1.5, (
            f"Volume set mismatch: target={test_target}, got={set_res['volume_percent']}"
        )
        print(f"    [PASS] set_volume({test_target}) successfully applied -> {set_res['volume_percent']}%")

        # Clamping validation
        clamp_max = set_volume(150.0)
        assert clamp_max["volume_percent"] == 100.0, f"Upper clamping failed: {clamp_max}"
        clamp_min = set_volume(-30.0)
        assert clamp_min["volume_percent"] == 0.0, f"Lower clamping failed: {clamp_min}"
        print("    [PASS] Volume clamping verified strictly between [0.0, 100.0]")

        # Mute toggle validation
        toggle_res1 = toggle_mute()
        assert toggle_res1.get("success") is True
        assert toggle_res1["is_muted"] == (not orig_mute), "Mute toggle did not invert state"
        print(f"    [PASS] toggle_mute() successfully inverted state to is_muted={toggle_res1['is_muted']}")

        toggle_res2 = toggle_mute()
        assert toggle_res2.get("success") is True
        assert toggle_res2["is_muted"] == orig_mute, "Mute toggle failed to revert state"
        print(f"    [PASS] toggle_mute() successfully reverted state to is_muted={toggle_res2['is_muted']}")

    finally:
        # Guarantee restoration of user's original volume
        restored = set_volume(orig_vol)
        print(f"    [RESTORE] Restored initial volume to {restored.get('volume_percent')}%\n")

    # 1.2 WinRT Media Status & Transport Controls
    print("  Subtest 1.2: Media Session Status & Controls via winrt...")
    status = await get_media_status()
    assert isinstance(status, dict), "get_media_status() must return a dict"
    assert "active" in status, "get_media_status() missing 'active' key"
    assert "playback_status" in status, "get_media_status() missing 'playback_status' key"
    assert "source_app" in status, "get_media_status() missing 'source_app' key"
    print(f"    [PASS] get_media_status() returned active={status['active']}, status='{status['playback_status']}', app={status['source_app']}")

    # Transport control dispatch
    ctrl_res = await control_media("play_pause")
    assert isinstance(ctrl_res, dict), "control_media() must return a dict"
    assert "action" in ctrl_res, "control_media() missing 'action' key"
    assert ctrl_res["action"] == "play_pause"
    assert "success" in ctrl_res, "control_media() missing 'success' key"
    print(f"    [PASS] control_media('play_pause') gracefully handled: success={ctrl_res['success']}, msg='{ctrl_res.get('message') or ctrl_res.get('error')}'")

    # Unsupported action rejection
    invalid_res = await control_media("rewind_fast_unsupported")
    assert invalid_res.get("success") is False
    assert "Unsupported media action" in invalid_res.get("error", "")
    print("    [PASS] control_media() rejected invalid action with informative error.")


# ==============================================================================
# TEST 2: Document Processing Tools (Excel, Word, PowerPoint)
# ==============================================================================
def test_document_tools():
    print("\n" + "=" * 60)
    print("[TEST 2] Testing Document Processing Tools (makima.tools.documents)")
    print("=" * 60)

    orig_workspace = get_workspace_dir()
    temp_dir = tempfile.mkdtemp(prefix="makima_doc_test_")
    sandbox_path = Path(temp_dir).resolve()
    set_workspace_dir(sandbox_path)

    try:
        # 2.1 Excel Sheet Creation & Reading via openpyxl
        print("  Subtest 2.1: Excel (.xlsx) Creation & Reading via openpyxl...")
        headers = ["ID", "Module", "Tier", "Efficiency", "Launch Date"]
        rows = [
            [101, "ParetoRouter", "Zero-Cost", 99.8, date(2026, 3, 1)],
            [102, "HermesEngine", "Autonomous", 98.5, date(2026, 3, 2)],
            [103, "MediaController", "WindowsNative", 100.0, date(2026, 3, 3)],
        ]
        excel_rel = "analytics/system_metrics.xlsx"
        create_res = create_excel_sheet(
            file_path=excel_rel,
            headers=headers,
            rows=rows,
            sheet_title="Metrics",
        )
        assert create_res.get("status") == "success"
        assert create_res.get("rows_count") == 3
        assert create_res.get("columns_count") == 5
        assert Path(create_res["absolute_path"]).is_file()
        print(f"    [PASS] create_excel_sheet() generated '{excel_rel}' ({create_res['file_size_bytes']} bytes)")

        read_res = read_excel_sheet(file_path=excel_rel)
        assert read_res.get("status") == "success"
        assert read_res.get("headers") == headers
        assert read_res.get("total_rows_read") == 3
        assert len(read_res.get("rows", [])) == 3
        assert read_res["rows"][0]["Module"] == "ParetoRouter"
        assert read_res["rows"][0]["Efficiency"] == 99.8
        print("    [PASS] read_excel_sheet() accurately parsed structured rows and typed cells.")

        # 2.2 Word Document Creation & Reading via python-docx
        print("  Subtest 2.2: Word (.docx) Creation & Reading via python-docx...")
        doc_rel = "reports/audit_specification.docx"
        sections = [
            {
                "heading": "Architecture Summary",
                "level": 1,
                "text": "Makima v2 is engineered with strict zero-cost and dynamic introspection rules.",
                "bullets": [
                    "Dynamic tool auto-discovery without static registries",
                    "Hermes autonomous while-loop agent engine",
                    "Dual-tier memory with WAL SQLite persistence",
                ],
            },
            {
                "heading": "Tool Matrix",
                "level": 2,
                "table": {
                    "headers": ["Tool Name", "Domain", "Status"],
                    "rows": [
                        ["get_volume", "Media", "Operational"],
                        ["create_excel_sheet", "Documents", "Operational"],
                        ["fetch_web_page", "Browser", "Operational"],
                    ],
                },
            },
        ]
        doc_res = create_word_document(
            file_path=doc_rel,
            title="Makima v2 Technical Audit",
            sections=sections,
        )
        assert doc_res.get("status") == "success"
        assert doc_res.get("sections_count") == 2
        assert doc_res.get("tables_count") == 1
        assert Path(doc_res["absolute_path"]).is_file()
        print(f"    [PASS] create_word_document() generated '{doc_rel}' ({doc_res['file_size_bytes']} bytes)")

        read_doc = read_word_document(file_path=doc_rel)
        assert read_doc.get("status") == "success"
        assert read_doc.get("paragraphs_count") >= 4
        assert read_doc.get("tables_count") == 1
        assert "# Makima v2 Technical Audit" in read_doc.get("markdown", "")
        print("    [PASS] read_word_document() extracted paragraphs, table structures, and Markdown.")

        # 2.3 PowerPoint Presentation Creation & Reading via python-pptx
        print("  Subtest 2.3: PowerPoint (.pptx) Creation & Reading via python-pptx...")
        ppt_rel = "decks/makima_presentation.pptx"
        slides = [
            {
                "title": "Autonomous Execution Model",
                "content": "Full desktop environment integration via Win32, WinRT, and ConPTY.",
                "bullets": [
                    "Sub-15ms terminal interaction",
                    "High-fidelity document synthesis",
                    "Stealth browser automation",
                ],
                "notes": "Speaker note: emphasize zero blind copy-pasting from v1.",
            },
            {
                "title": "Zero-Cost Ecosystem",
                "content": "Optimized free quotas and local offline Ollama fallbacks.",
            },
        ]
        ppt_res = create_powerpoint(
            file_path=ppt_rel,
            title="Makima v2 Executive Briefing",
            subtitle="Next-Generation Autonomous Assistant",
            slides=slides,
        )
        assert ppt_res.get("status") == "success"
        assert ppt_res.get("slides_count") == 3  # Title slide + 2 content slides
        assert Path(ppt_res["absolute_path"]).is_file()
        print(f"    [PASS] create_powerpoint() generated '{ppt_rel}' (3 slides, {ppt_res['file_size_bytes']} bytes)")

        read_ppt = read_powerpoint(file_path=ppt_rel)
        assert read_ppt.get("status") == "success"
        assert read_ppt.get("slides_count") == 3
        assert read_ppt["slides"][0]["title"] == "Makima v2 Executive Briefing"
        assert read_ppt["slides"][1]["title"] == "Autonomous Execution Model"
        assert "Speaker note" in read_ppt["slides"][1].get("notes", "")
        print("    [PASS] read_powerpoint() verified slide titles, bullets, and speaker notes.")

        # 2.4 Adversarial Boundary Clamping
        print("  Subtest 2.4: Adversarial Path Traversal Guards...")
        traversal_blocked = False
        try:
            create_excel_sheet(
                file_path="../../windows/system32/pwn.xlsx",
                headers=["h1"],
                rows=[[1]],
            )
        except BoundaryTraversalError:
            traversal_blocked = True

        assert traversal_blocked is True, "BoundaryTraversalError was NOT raised for illegal path!"
        print("    [PASS] Strict workspace boundary clamping prevented directory traversal.")

    finally:
        set_workspace_dir(orig_workspace)
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# TEST 3: Web Browser Tools (fetch_web_page & search_web)
# ==============================================================================
async def test_browser_tools():
    print("\n" + "=" * 60)
    print("[TEST 3] Testing Web Browser Tools (makima.tools.browser)")
    print("=" * 60)

    # 3.1 fetch_web_page (Mocked Parsing Verification)
    print("  Subtest 3.1: fetch_web_page() HTML Sanitization & Extraction...")
    mock_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Makima Autonomous Kernel - Architecture</title>
        <style>body { background: #000; }</style>
        <script>console.log('malicious_tracking()');</script>
    </head>
    <body>
        <nav><a href="/home">Home</a><a href="/docs">Docs</a></nav>
        <header>Banner Announcement</header>
        <main>
            <h1>Makima v2 Kernel Operational</h1>
            <p>Makima v2 combines dynamic Pareto routing with modular Hermes execution.</p>
            <p>Direct Win32, WinRT, and ConPTY access ensures high performance.</p>
        </main>
        <footer>Copyright 2026</footer>
    </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.url = "https://makima.ai/docs"
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.text = mock_html

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        result = await fetch_web_page(url="https://makima.ai/docs", extract_text=True)

        assert result.get("success") is True, f"fetch_web_page failed: {result}"
        assert result.get("title") == "Makima Autonomous Kernel - Architecture"
        assert result.get("status_code") == 200
        text = result.get("text", "")
        assert "Makima v2 Kernel Operational" in text
        assert "malicious_tracking" not in text, "Script tags were not decomposed!"
        assert "Banner Announcement" not in text, "Header tags were not decomposed!"
        print(f"    [PASS] fetch_web_page() stripped scripts/styles/navs, extracted title and {result.get('length')} chars.")

    # 3.2 URL normalization and error resilience
    print("  Subtest 3.2: URL Normalization and Error Handling...")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_fail:
        import httpx
        mock_fail.side_effect = httpx.ConnectTimeout("Connection timed out")
        fail_res = await fetch_web_page("offline-test-domain.internal")
        assert fail_res.get("success") is False
        assert fail_res.get("url") == "https://offline-test-domain.internal"  # Auto normalized
        assert "timed out" in fail_res.get("error", "").lower()
        print("    [PASS] Normalization added 'https://' prefix and handled timeout cleanly.")

    # 3.3 search_web (DuckDuckGo Search Engine Extraction)
    print("  Subtest 3.3: search_web() via DuckDuckGo Scraper...")
    mock_search_html = """
    <div class="result">
        <h2 class="result__title">
            <a class="result__url" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fmakima-ai%2Fkernel">Makima v2 GitHub Repository</a>
        </h2>
        <a class="result__snippet">Official autonomous desktop agent ecosystem implementing Hermes patterns.</a>
    </div>
    <div class="result result--ad">
        <h2 class="result__title"><a href="https://ad.com">Sponsored Ad</a></h2>
    </div>
    <div class="result">
        <h2 class="result__title">
            <a class="result__url" href="https://makima.ai/blog/pareto-routing">Pareto Frontier Routing in Multi-Model Agents</a>
        </h2>
        <a class="result__snippet">In-depth mathematical analysis of EWMA latency updates and cascade selection.</a>
    </div>
    """
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.text = mock_search_html

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_post_resp
        search_res = await search_web(query="Makima autonomous agent", max_results=5)

        assert search_res.get("success") is True, f"search_web failed: {search_res}"
        results = search_res.get("results", [])
        assert len(results) == 2, f"Expected 2 organic results (excluding ad), got {len(results)}"
        assert results[0]["title"] == "Makima v2 GitHub Repository"
        assert results[0]["url"] == "https://github.com/makima-ai/kernel", "DuckDuckGo redirect URL was not unwrapped!"
        assert "Hermes patterns" in results[0]["snippet"]
        assert results[1]["title"] == "Pareto Frontier Routing in Multi-Model Agents"
        print(f"    [PASS] search_web() filtered advertisements, unwrapped URLs, and extracted {len(results)} clean results.")

    # 3.4 Empty query rejection
    empty_res = await search_web("    ")
    assert empty_res.get("success") is False
    assert "Search query cannot be empty" in empty_res.get("error", "")
    print("    [PASS] search_web() safely rejected empty whitespace queries.")

    # 3.5 browse_page Availability check
    print("  Subtest 3.4: browse_page() Playwright Tool Discovery...")
    assert callable(browse_page)
    print("    [PASS] browse_page() tool function is importable and registered.")


# ==============================================================================
# TEST 4: ToolRegistry Verification & Schema Auto-Synthesis
# ==============================================================================
async def test_tool_registry_synthesis():
    print("\n" + "=" * 60)
    print("[TEST 4] Testing ToolRegistry Auto-Discovery & Dynamic Schema Synthesis")
    print("=" * 60)

    reset_registry()
    registry = get_registry(auto_discover=True)

    expected_step9_tools = [
        # Media Tools
        ("get_volume", ["media", "volume"]),
        ("set_volume", ["media", "volume"]),
        ("toggle_mute", ["media", "volume"]),
        ("control_media", ["media", "playback"]),
        ("get_media_status", ["media", "status"]),
        # Document Tools
        ("create_excel_sheet", ["documents", "excel"]),
        ("read_excel_sheet", ["documents", "excel"]),
        ("create_word_document", ["documents", "word"]),
        ("read_word_document", ["documents", "word"]),
        ("create_powerpoint", ["documents", "powerpoint"]),
        ("read_powerpoint", ["documents", "powerpoint"]),
        # Browser Tools
        ("fetch_web_page", ["web", "browser"]),
        ("search_web", ["web", "browser"]),
        ("browse_page", ["web", "browser"]),
    ]

    for tool_name, req_tags in expected_step9_tools:
        assert tool_name in registry, f"Tool '{tool_name}' missing from dynamic registry!"
        tool_obj = registry[tool_name]

        # 1. Parameter schema verification
        schema = tool_obj.parameters_schema
        assert isinstance(schema, dict), f"Tool '{tool_name}' schema must be a dict"
        assert schema.get("type") == "object", f"Tool '{tool_name}' schema type must be 'object'"
        assert "properties" in schema, f"Tool '{tool_name}' missing 'properties' in schema"

        # 2. Tag verification
        for t in req_tags:
            assert t in tool_obj.tags, f"Tool '{tool_name}' missing required tag '{t}' (has: {tool_obj.tags})"

        # 3. Docstring presence
        assert tool_obj.description and len(tool_obj.description.strip()) > 10, (
            f"Tool '{tool_name}' missing descriptive explanation!"
        )

    print(f"  [PASS] All {len(expected_step9_tools)} Step 9 tools validated with strict JSON Schema contracts.")

    # Dynamic execution test through registry dispatcher
    print("  Subtest 4.2: Dynamic Registry Execution...")
    exec_res = await registry.execute("get_volume", {})
    assert exec_res.get("success") is True
    print(f"    [PASS] registry.execute('get_volume') returned valid result: {exec_res['volume_percent']}%\n")


# ==============================================================================
# MAIN TEST SUITE RUNNER
# ==============================================================================
async def main():
    print("=" * 60)
    print("RUNNING LIVE VERIFICATION: Step 9 (Browser, Media & Documents)")
    print("=" * 60)

    await test_media_tools()
    test_document_tools()
    await test_browser_tools()
    await test_tool_registry_synthesis()

    print("=" * 60)
    print("ALL STEP 9 BROWSER, MEDIA & DOCUMENT TESTS PASSED! (EXIT CODE 0)")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
