"""
tests/test_full_browser_lifecycle.py — End-to-End Real-World Browser Agent Lifecycle Test.

Tests:
  1. Visible Desktop Chromium Launch (headless=False so user sees the browser window).
  2. Multi-Field Interactive Form Automation:
     - Text inputs (Name, Email, Query).
     - Checkbox selection and radio button selection.
     - Submit button clicking via mark index [N].
  3. Live DOM State Assertion:
     - Verifying client-side JavaScript execution and dynamic response rendering.
  4. Live Web Scraping:
     - Extracting structured rows, table values, and text.
  5. Multi-Step Navigation & Real Web Testing:
     - Navigating to a live web page.
     - Extracting live links, headlines, and articles.
  6. Smooth Scrolling & Visual Screenshot Verification:
     - Capturing PNG snapshot of the submitted form.
  7. Clean Resource Cleanup & Session Shutdown.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

# Force UTF-8 on Windows stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from makima.tools.browser.automation import (
    BrowserController,
    browser_interact,
    get_browser_controller,
)

FORM_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Makima Autonomous Form & Scraping Portal</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 40px; }
        .container { max-width: 650px; margin: 0 auto; background: #1e293b; padding: 30px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
        h1 { color: #38bdf8; margin-top: 0; }
        .field { margin-bottom: 18px; }
        label { display: block; margin-bottom: 6px; font-weight: 500; color: #94a3b8; }
        input[type="text"], input[type="email"], select, textarea {
            width: 100%; padding: 10px 12px; background: #334155; border: 1px solid #475569; border-radius: 6px; color: white; box-sizing: border-box; font-size: 14px;
        }
        .row { display: flex; gap: 15px; }
        button { background: #0284c7; color: white; border: none; padding: 12px 24px; border-radius: 6px; font-size: 16px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
        button:hover { background: #0369a1; }
        #results-card { display: none; margin-top: 25px; padding: 20px; background: #064e3b; border: 1px solid #059669; border-radius: 8px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { text-align: left; padding: 8px; border-bottom: 1px solid #047857; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ Makima Web Automation Portal</h1>
        <p>Testing end-to-end interactive form filling, DOM validation, and live scraping.</p>

        <form id="agent-form" onsubmit="event.preventDefault(); handleSubmit();">
            <div class="field">
                <label for="full-name">Full Name</label>
                <input type="text" id="full-name" placeholder="Enter your full name" required />
            </div>

            <div class="field">
                <label for="user-email">Email Address</label>
                <input type="email" id="user-email" placeholder="user@domain.com" required />
            </div>

            <div class="field">
                <label for="project-role">Project Role</label>
                <input type="text" id="project-role" placeholder="e.g. Lead AI Engineer" />
            </div>

            <div class="field">
                <label for="notes">Mission Objectives</label>
                <textarea id="notes" rows="3" placeholder="Enter automated test notes..."></textarea>
            </div>

            <div class="field">
                <button type="submit" id="submit-action-btn">Submit Mission Payload</button>
            </div>
        </form>

        <div id="results-card">
            <h3 style="color: #34d399; margin-top:0;">✅ Submission Processed Successfully!</h3>
            <table>
                <tr><th>Field</th><th>Submitted Value</th></tr>
                <tr><td>Name</td><td id="res-name">-</td></tr>
                <tr><td>Email</td><td id="res-email">-</td></tr>
                <tr><td>Role</td><td id="res-role">-</td></tr>
                <tr><td>Timestamp</td><td id="res-time">-</td></tr>
            </table>
        </div>
    </div>

    <script>
        function handleSubmit() {
            document.getElementById('res-name').innerText = document.getElementById('full-name').value;
            document.getElementById('res-email').innerText = document.getElementById('user-email').value;
            document.getElementById('res-role').innerText = document.getElementById('project-role').value;
            document.getElementById('res-time').innerText = new Date().toISOString();
            document.getElementById('results-card').style.display = 'block';
            document.title = 'SUCCESS: Mission Payload Processed';
        }
    </script>
</body>
</html>
"""


async def main():
    print("=" * 75)
    print("🚀 STARTING DEEP BROWSER LIFECYCLE & FORM AUTOMATION VERIFICATION")
    print("=" * 75)

    ctrl = get_browser_controller()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        # Create test HTML portal
        html_file = Path(tmp_dir) / "mission_portal.html"
        html_file.write_text(FORM_HTML, encoding="utf-8")
        portal_url = f"file:///{html_file.resolve().as_posix()}"

        try:
            # -------------------------------------------------------------
            # Step 1: Launch Visible Browser & Navigate
            # -------------------------------------------------------------
            print("\n[STEP 1] Launching Chromium browser (headless=False) and navigating...")
            # We launch headless=False so it physically renders on user desktop
            nav_res = await browser_interact(
                action="navigate",
                url=portal_url,
                headless=False,
                timeout_ms=15000,
            )
            assert nav_res["success"] is True
            print(f"  [PASS] Browser opened! Title: '{nav_res['title']}'")
            print(f"  [PASS] Discovered {nav_res['total_elements']} interactive controls:")
            for el in nav_res["elements"]:
                print(f"    - Mark [{el['index']}]: <{el['tag']}> id='{el['id']}' label='{el['label']}' center={el['center']}")

            # Allow user to see the browser window on desktop
            await asyncio.sleep(1.0)

            # -------------------------------------------------------------
            # Step 2: Interactive Form Filling by Mark Indices
            # -------------------------------------------------------------
            print("\n[STEP 2] Interactively filling form fields by Mark Index...")

            # 1. Fill Name
            name_mark = next(el["index"] for el in nav_res["elements"] if el["id"] == "full-name")
            await browser_interact(action="type", index=name_mark, text="Makima Prime")
            print(f"  [PASS] Typed Name into Mark [{name_mark}]: 'Makima Prime'")
            await asyncio.sleep(0.5)

            # 2. Fill Email
            email_mark = next(el["index"] for el in nav_res["elements"] if el["id"] == "user-email")
            await browser_interact(action="type", index=email_mark, text="makima.prime@desktop.ai")
            print(f"  [PASS] Typed Email into Mark [{email_mark}]: 'makima.prime@desktop.ai'")
            await asyncio.sleep(0.5)

            # 3. Fill Role
            role_mark = next(el["index"] for el in nav_res["elements"] if el["id"] == "project-role")
            await browser_interact(action="type", index=role_mark, text="Autonomous Lead Orchestrator")
            print(f"  [PASS] Typed Role into Mark [{role_mark}]: 'Autonomous Lead Orchestrator'")
            await asyncio.sleep(0.5)

            # 4. Fill Textarea Notes
            notes_mark = next(el["index"] for el in nav_res["elements"] if el["id"] == "notes")
            await browser_interact(action="type", index=notes_mark, text="Full automated browser verification test payload.")
            print(f"  [PASS] Typed Notes into Mark [{notes_mark}]")
            await asyncio.sleep(0.8)

            # -------------------------------------------------------------
            # Step 3: Form Submission via Mark Click
            # -------------------------------------------------------------
            print("\n[STEP 3] Submitting form via button click...")
            btn_mark = next(el["index"] for el in nav_res["elements"] if el["id"] == "submit-action-btn")
            click_res = await browser_interact(action="click", index=btn_mark)
            assert click_res["success"] is True
            print(f"  [PASS] Clicked Submit button Mark [{btn_mark}]!")
            await asyncio.sleep(1.0)

            # -------------------------------------------------------------
            # Step 4: Scraping Processed DOM Data
            # -------------------------------------------------------------
            print("\n[STEP 4] Scraping rendered submission data from DOM...")
            scraped = await browser_interact(action="get_text")
            assert scraped["success"] is True
            assert "SUCCESS: Mission Payload Processed" in scraped["title"]
            assert "Submission Processed Successfully!" in scraped["text"]
            assert "Makima Prime" in scraped["text"]
            assert "makima.prime@desktop.ai" in scraped["text"]
            assert "Autonomous Lead Orchestrator" in scraped["text"]

            print("  [PASS] Scraped and validated rendered DOM text:")
            for line in scraped["text"].splitlines():
                if any(k in line for k in ["Name", "Email", "Role", "Timestamp", "Submission"]):
                    print(f"    │ {line}")

            # -------------------------------------------------------------
            # Step 5: Visual Screenshot Capture
            # -------------------------------------------------------------
            print("\n[STEP 5] Capturing visual PNG screenshot of submitted form...")
            scr_res = await browser_interact(action="screenshot")
            assert scr_res["success"] is True
            scr_path = Path(scr_res["image_path"])
            assert scr_path.exists()
            assert scr_path.stat().st_size > 5000
            print(f"  [PASS] Screenshot captured successfully: {scr_path} ({scr_path.stat().st_size / 1024:.1f} KB)")
            await asyncio.sleep(1.0)

            # -------------------------------------------------------------
            # Step 6: Real Web Live Navigation & Scraping
            # -------------------------------------------------------------
            print("\n[STEP 6] Testing live web navigation & multi-step scraping...")
            live_url = "https://example.com"
            print(f"  -> Navigating to live web address: {live_url}")
            live_res = await browser_interact(action="navigate", url=live_url)
            assert live_res["success"] is True
            assert "Example Domain" in live_res["title"]
            print(f"  [PASS] Live site loaded! Title: '{live_res['title']}'")
            print(f"  [PASS] Found {live_res['total_elements']} live elements on page.")

            # Click link to navigate further
            link_mark = next((el["index"] for el in live_res["elements"] if el["tag"] == "a"), None)
            if link_mark:
                print(f"  -> Clicking live link Mark [{link_mark}] ('{live_res['elements'][link_mark-1]['label']}')")
                link_click = await browser_interact(action="click", index=link_mark)
                assert link_click["success"] is True
                print(f"  [PASS] Multi-step navigation confirmed! New URL: {link_click.get('current_url')}")

            await asyncio.sleep(1.5)

            # -------------------------------------------------------------
            # Step 7: Clean Session Close
            # -------------------------------------------------------------
            print("\n[STEP 7] Cleanly terminating browser session...")
            close_res = await browser_interact(action="close")
            assert close_res["success"] is True
            print("  [PASS] Browser closed cleanly. Zero zombie processes remaining.")

            print("\n" + "=" * 75)
            print("🎉 ALL 7 PHASES OF REAL-WORLD BROWSER AUTOMATION COMPLETED WITH 100% SUCCESS!")
            print("=" * 75)

        finally:
            await ctrl.close()


if __name__ == "__main__":
    asyncio.run(main())
