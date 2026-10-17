"""
Verification Test Suite for Step 29: Instant Windows App Controller via AppOpener.
Tests:
  1. App Discovery via get_installed_applications:
     - Discovers registered Windows store & Win32 applications catalog.
     - Validates non-empty catalog and common Windows applications.
  2. Safe Resolution & Dry-Run Mode:
     - Dry-run launch of standard applications (e.g. 'notepad').
     - Dry-run launch of registered protocol URIs (e.g. 'calc:', 'spotify:', 'ms-settings:').
     - Dry-run validation of unknown/nonexistent applications.
  3. Live Application Launch & Lifecycle Control:
     - Launch Windows Calculator via launch_application.
     - Verify process existence via psutil.
     - Terminate application via terminate_application.
     - Verify clean process termination.
  4. Robust Error Handling:
     - Empty or whitespace application names.
     - Terminating an application that is not currently running.
  5. Dynamic Tool Registry Auto-Discovery & Schema Validation:
     - Auto-discovery of 'launch_application' and 'terminate_application'.
     - Schema generation and async execution via ToolRegistry.execute.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import psutil

from makima.tools.os.app_opener import (
    get_installed_applications,
    launch_application,
    terminate_application,
)
from makima.tools.registry import get_registry, reset_registry


def test_app_discovery():
    print("\n" + "=" * 60)
    print("[TEST 1] App Discovery (makima.tools.os.app_opener)")
    print("=" * 60)

    apps = get_installed_applications()
    assert isinstance(apps, list), "get_installed_applications should return a list"
    assert len(apps) > 0, "AppOpener should discover at least one installed application"

    print(f"  [PASS] Discovered {len(apps)} installed applications via AppOpener catalog.")
    sample = apps[:5]
    print(f"         Sample catalog entries: {sample}")

    # Verify presence of standard Windows applications
    assert any("calc" in a or "calculator" in a for a in apps), "Calculator should be in catalog"
    print("  [PASS] Catalog contains standard Windows applications.")


def test_dry_run_resolution():
    print("\n" + "=" * 60)
    print("[TEST 2] Safe Resolution & Dry-Run Mode")
    print("=" * 60)

    # 1. Standard application dry-run
    res_notepad = launch_application("notepad", dry_run=True)
    assert res_notepad["success"] is True, f"Dry-run for notepad failed: {res_notepad}"
    assert res_notepad["dry_run"] is True
    assert "target" in res_notepad
    print(f"  [PASS] Dry-run launch_application('notepad'): target='{res_notepad['target']}'")

    # 2. Registered URI protocol dry-run (calc:)
    res_proto = launch_application("calc:", dry_run=True)
    assert res_proto["success"] is True
    assert res_proto["method"] == "protocol"
    assert res_proto["dry_run"] is True
    print(f"  [PASS] Dry-run launch_application('calc:'): protocol verified.")

    # 3. Spotify protocol dry-run
    res_spotify = launch_application("spotify:", dry_run=True)
    assert res_spotify["success"] is True
    assert res_spotify["method"] == "protocol"
    print(f"  [PASS] Dry-run launch_application('spotify:'): protocol verified.")

    # 4. Alias resolution (calc -> calculator)
    res_calc = launch_application("calc", dry_run=True)
    assert res_calc["success"] is True
    assert res_calc["target"] == "calculator"
    print(f"  [PASS] Dry-run launch_application('calc'): correctly mapped to 'calculator'.")

    # 5. Non-existent application resolution failure
    res_fake = launch_application("completely_fake_app_xyz_9999", dry_run=True)
    assert res_fake["success"] is False
    assert "could not be resolved" in res_fake["error"].lower() or "not found" in res_fake["error"].lower()
    print(f"  [PASS] Dry-run on non-existent app failed safely: {res_fake['error']}")



def test_live_launch_and_termination():
    print("\n" + "=" * 60)
    print("[TEST 3] Live Application Launch & Lifecycle Control")
    print("=" * 60)

    # Pre-cleanup: Ensure calculator is not running before test
    try:
        terminate_application("calculator")
    except Exception:
        pass
    time.sleep(1)

    # Launch Calculator live
    launch_res = launch_application("calculator")
    assert launch_res["success"] is True, f"Live launch of calculator failed: {launch_res}"
    print(f"  [PASS] Live launch_application('calculator') succeeded: {launch_res.get('message')}")

    # Wait for process to spawn
    time.sleep(2)

    # Verify process is running via psutil
    calc_procs = [
        p for p in psutil.process_iter(["pid", "name"])
        if "calc" in (p.info["name"] or "").lower()
    ]
    assert len(calc_procs) > 0, "Calculator process should be active in psutil process table"
    calc_pid = calc_procs[0].info["pid"]
    calc_name = calc_procs[0].info["name"]
    print(f"  [PASS] Verified active process: {calc_name} (PID: {calc_pid})")

    # Terminate application live
    term_res = terminate_application("calculator")
    assert term_res["success"] is True, f"Live termination of calculator failed: {term_res}"
    print(f"  [PASS] Live terminate_application('calculator') succeeded: {term_res.get('message')}")

    # Wait for process termination
    time.sleep(1.5)
    remaining_calcs = [
        p for p in psutil.process_iter(["pid", "name"])
        if "calc" in (p.info["name"] or "").lower()
    ]
    assert len(remaining_calcs) == 0, f"Calculator process still running after termination: {remaining_calcs}"
    print("  [PASS] Confirmed process completely terminated.")


def test_error_handling():
    print("\n" + "=" * 60)
    print("[TEST 4] Robust Error Handling")
    print("=" * 60)

    # 1. Empty app_name on launch
    empty_launch = launch_application("")
    assert empty_launch["success"] is False
    assert "empty" in empty_launch["error"].lower()
    print(f"  [PASS] launch_application('') rejected: {empty_launch['error']}")

    # 2. Whitespace app_name on launch
    ws_launch = launch_application("   ")
    assert ws_launch["success"] is False
    assert "empty" in ws_launch["error"].lower()
    print(f"  [PASS] launch_application('   ') rejected: {ws_launch['error']}")

    # 3. Empty app_name on terminate
    empty_term = terminate_application("")
    assert empty_term["success"] is False
    assert "empty" in empty_term["error"].lower()
    print(f"  [PASS] terminate_application('') rejected: {empty_term['error']}")

    # 4. Terminate an app that is not running
    fake_term = terminate_application("nonexistent_app_makima_test_9999")
    assert fake_term["success"] is False
    print(f"  [PASS] terminate_application on non-running app handled safely: {fake_term['error']}")


async def test_tool_registry_auto_discovery():
    print("\n" + "=" * 60)
    print("[TEST 5] Dynamic Tool Registry Auto-Discovery")
    print("=" * 60)

    reset_registry()
    reg = get_registry(auto_discover=True)

    expected_tools = ["launch_application", "terminate_application"]
    for tool_name in expected_tools:
        assert tool_name in reg, f"Expected tool '{tool_name}' not discovered in ToolRegistry"
        tool_obj = reg[tool_name]
        schema = tool_obj.to_dict()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == tool_name
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]
        print(f"  [PASS] Tool '{tool_name}' auto-discovered with tags: {tool_obj.tags}")

    # Asynchronous execution via registry
    exec_res = await reg.execute(
        "launch_application",
        {"app_name": "calc:", "dry_run": True},
    )
    assert isinstance(exec_res, dict)
    assert exec_res.get("success") is True
    print(f"  [PASS] reg.execute('launch_application', dry_run=True) succeeded: {exec_res.get('method')}")


def main():
    print("Starting Standalone Verification Test Suite for AppOpener Controller (Step 29)...")
    t0 = time.time()

    test_app_discovery()
    test_dry_run_resolution()
    test_live_launch_and_termination()
    test_error_handling()
    asyncio.run(test_tool_registry_auto_discovery())

    elapsed = round(time.time() - t0, 2)
    print("\n" + "=" * 60)
    print(f"ALL TESTS PASSED SUCCESSFULLY in {elapsed}s (Exit Code: 0)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
