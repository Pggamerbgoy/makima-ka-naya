"""
tests/verify_interactive_browser.py — Verification Suite for SOTA Interactive Browser Controller.

Tests:
  1. ToolRegistry discovery and OpenAI schema generation for `browser_interact`.
  2. Multi-step browser session lifecycle:
     - Navigation to dynamic HTML page.
     - Indexed interactive elements extraction ([1], [2], ...).
     - Input field typing by mark index.
     - Button clicking by mark index.
     - Smooth page scrolling.
     - Full viewport screenshot capture.
     - Visible text extraction.
     - Clean session shutdown.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from makima.tools.browser.automation import (
    browser_interact,
    get_browser_controller,
)
from makima.tools.registry import get_registry, reset_registry

SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Makima Interactive Browser Test</title>
    <style>
        body { font-family: sans-serif; padding: 30px; height: 1500px; background: #f0f4f8; }
        .box { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); width: 400px; }
        input { width: 90%; padding: 8px; margin: 10px 0; }
        button { padding: 10px 20px; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }
        .result { margin-top: 15px; font-weight: bold; color: #16a34a; }
    </style>
</head>
<body>
    <div class="box">
        <h1>Makima Web Agent</h1>
        <p>Testing interactive DOM automation and indexed clicking.</p>
        <input id="search-input" placeholder="Search query or text..." />
        <button id="submit-btn" onclick="document.getElementById('out').innerText = 'Submitted: ' + document.getElementById('search-input').value;">Search Makima</button>
        <div id="out" class="result">Waiting...</div>
        <p><a id="doc-link" href="#section2">Documentation Link</a></p>
    </div>
    <div style="margin-top: 800px;" id="section2">
        <h2>Bottom Section</h2>
        <button id="bottom-btn" onclick="alert('Scrolled down!')">Bottom Action</button>
    </div>
</body>
</html>
"""


async def run_verification():
    print("=" * 70)
    print("RUNNING VERIFICATION: SOTA Interactive Visible Browser Controller")
    print("=" * 70)

    # -------------------------------------------------------------
    # Stage 1: Tool Registry Discovery
    # -------------------------------------------------------------
    print("\n[STAGE 1] Testing ToolRegistry discovery...")
    reset_registry()
    reg = get_registry(auto_discover=True)

    assert reg.has("browser_interact"), "browser_interact not found in registry"
    tool_obj = reg.get("browser_interact")
    assert tool_obj is not None
    schema = tool_obj.to_schema(format="openai")
    assert schema["function"]["name"] == "browser_interact"
    assert "action" in schema["function"]["parameters"]["properties"]
    print("  [PASS] browser_interact tool discovered and schema generated.")

    # -------------------------------------------------------------
    # Setup: Create local test HTML page
    # -------------------------------------------------------------
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        test_file = Path(tmp_dir) / "test_browser.html"
        test_file.write_text(SAMPLE_HTML, encoding="utf-8")
        file_url = f"file:///{test_file.resolve().as_posix()}"

        ctrl = get_browser_controller()

        try:
            # ---------------------------------------------------------
            # Stage 2: Navigate & Ground Interactive Elements
            # ---------------------------------------------------------
            print("\n[STAGE 2] Testing action='navigate'...")
            # Run headless=True for automated testing in test environments
            nav_res = await browser_interact(action="navigate", url=file_url, headless=True)
            assert nav_res["success"] is True
            assert "Makima Interactive Browser Test" in nav_res["title"]
            assert nav_res["total_elements"] >= 3
            print(f"  [PASS] Navigated successfully! Found {nav_res['total_elements']} interactive elements.")
            for el in nav_res["elements"][:4]:
                print(f"    Mark [{el['index']}] <{el['tag']}> label='{el['label']}' center={el['center']}")

            # ---------------------------------------------------------
            # Stage 3: Type Text into Input by Mark Index
            # ---------------------------------------------------------
            print("\n[STAGE 3] Testing action='type' into input field...")
            # Find input element index
            input_idx = None
            for el in nav_res["elements"]:
                if el["tag"] == "input" or el["id"] == "search-input":
                    input_idx = el["index"]
                    break
            assert input_idx is not None, "Could not find input element mark"

            type_res = await browser_interact(action="type", index=input_idx, text="Makima SOTA Web Agent")
            assert type_res["success"] is True
            assert type_res["typed"] == "Makima SOTA Web Agent"
            print(f"  [PASS] Successfully typed into mark [{input_idx}].")

            # ---------------------------------------------------------
            # Stage 4: Click Button by Mark Index
            # ---------------------------------------------------------
            print("\n[STAGE 4] Testing action='click' on button...")
            btn_idx = None
            for el in nav_res["elements"]:
                if el["tag"] == "button" and "Search" in el["label"]:
                    btn_idx = el["index"]
                    break
            assert btn_idx is not None, "Could not find button element mark"

            click_res = await browser_interact(action="click", index=btn_idx)
            assert click_res["success"] is True
            print(f"  [PASS] Successfully clicked button mark [{btn_idx}].")

            # Verify that DOM was updated by button click
            text_res = await browser_interact(action="get_text")
            assert text_res["success"] is True
            assert "Submitted: Makima SOTA Web Agent" in text_res["text"]
            print("  [PASS] DOM state update confirmed (button click triggered JS handler).")

            # ---------------------------------------------------------
            # Stage 5: Scroll Page
            # ---------------------------------------------------------
            print("\n[STAGE 5] Testing action='scroll'...")
            scroll_res = await browser_interact(action="scroll", scroll_y=500)
            assert scroll_res["success"] is True
            assert scroll_res["scrolled_amount"] == 500
            print("  [PASS] Successfully scrolled page by 500px.")

            # ---------------------------------------------------------
            # Stage 6: Capture Screenshot
            # ---------------------------------------------------------
            print("\n[STAGE 6] Testing action='screenshot'...")
            scr_res = await browser_interact(action="screenshot")
            assert scr_res["success"] is True
            assert Path(scr_res["image_path"]).exists()
            assert Path(scr_res["image_path"]).stat().st_size > 0
            print(f"  [PASS] Captured browser screenshot: {scr_res['image_path']}")
            # Clean up test capture
            try:
                Path(scr_res["image_path"]).unlink()
            except Exception:
                pass

            # ---------------------------------------------------------
            # Stage 7: Clean Session Close
            # ---------------------------------------------------------
            print("\n[STAGE 7] Testing action='close'...")
            close_res = await browser_interact(action="close")
            assert close_res["success"] is True
            assert ctrl.is_active is False
            print("  [PASS] Browser session cleanly terminated.")

            print("\n" + "=" * 70)
            print("ALL 7 STAGES OF INTERACTIVE BROWSER VERIFICATION PASSED!")
            print("=" * 70)

        finally:
            await ctrl.close()


if __name__ == "__main__":
    asyncio.run(run_verification())
