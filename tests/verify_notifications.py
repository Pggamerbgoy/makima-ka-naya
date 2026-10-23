"""
Verification Test Suite for Step 30: Native Windows Desktop Toast Alerts via win11toast.
Tests:
  1. Standard Toast Dispatch:
     - Dispatches native Windows 10/11 Action Center alert with title and message.
     - Confirms non-blocking execution and dispatch status.
  2. Interactive Notification with Action Buttons:
     - Dispatches notification configured with action buttons (e.g. ['Accept', 'Decline']).
     - Confirms proper formatting and delivery.
  3. Notification with Speech Dialogue Synthesis:
     - Dispatches notification with optional dialogue parameter.
  4. Robust Input Validation & Error Handling:
     - Empty title rejection.
     - Empty message rejection.
     - Whitespace-only parameters.
  5. Tool Registry Auto-Discovery & Async Execution:
     - Auto-discovery of 'show_desktop_notification' in ToolRegistry.
     - Parameter schema verification (OpenAI/Gemini compliant).
     - Asynchronous execution via ToolRegistry.execute.
"""

import asyncio
import sys
import time
from pathlib import Path

# Add project root to sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.tools.os.notifications import show_desktop_notification
from makima.tools.registry import get_registry, reset_registry


def test_standard_notification_dispatch():
    print("\n" + "=" * 60)
    print("[TEST 1] Standard Toast Dispatch (makima.tools.os.notifications)")
    print("=" * 60)

    t0 = time.time()
    res = show_desktop_notification(
        title="Makima v2 Notification",
        message="System telemetry and desktop services operational.",
    )
    dispatch_time = time.time() - t0

    assert isinstance(res, dict), "show_desktop_notification must return a dict"
    assert res.get("success") is True, f"Notification dispatch failed: {res}"
    assert res.get("dispatched") is True
    assert res.get("title") == "Makima v2 Notification"
    assert "System telemetry" in res.get("message", "")
    assert dispatch_time < 2.0, f"Notification dispatch took too long ({dispatch_time}s); should be non-blocking"

    print(f"  [PASS] Dispatched standard toast alert in {dispatch_time:.3f}s: {res.get('status')}")


def test_interactive_notification_buttons():
    print("\n" + "=" * 60)
    print("[TEST 2] Interactive Notification with Action Buttons")
    print("=" * 60)

    res = show_desktop_notification(
        title="Deployment Approval",
        message="Ruflo Swarm requested approval for Step 30 deployment.",
        buttons=["Approve", "Decline"],
    )

    assert res.get("success") is True, f"Button notification dispatch failed: {res}"
    assert res.get("buttons") == ["Approve", "Decline"]
    assert res.get("dispatched") is True
    print(f"  [PASS] Dispatched interactive notification with buttons: {res.get('buttons')}")


def test_notification_with_dialogue():
    print("\n" + "=" * 60)
    print("[TEST 3] Notification with Speech Dialogue Parameter")
    print("=" * 60)

    res = show_desktop_notification(
        title="Audio Alert",
        message="Voice synthesis alert dispatched.",
        dialogue="Makima Step 30 verified.",
    )

    assert res.get("success") is True, f"Dialogue notification failed: {res}"
    assert res.get("dialogue") == "Makima Step 30 verified."
    assert res.get("dispatched") is True
    print(f"  [PASS] Dispatched notification with dialogue: '{res.get('dialogue')}'")


def test_error_handling():
    print("\n" + "=" * 60)
    print("[TEST 4] Robust Input Validation & Error Handling")
    print("=" * 60)

    # 1. Empty title
    empty_title = show_desktop_notification(title="", message="Valid message")
    assert empty_title.get("success") is False
    assert "title" in empty_title.get("error", "").lower()
    print(f"  [PASS] Empty title rejected: {empty_title['error']}")

    # 2. Whitespace title
    ws_title = show_desktop_notification(title="   ", message="Valid message")
    assert ws_title.get("success") is False
    assert "title" in ws_title.get("error", "").lower()
    print(f"  [PASS] Whitespace title rejected: {ws_title['error']}")

    # 3. Empty message
    empty_msg = show_desktop_notification(title="Valid title", message="")
    assert empty_msg.get("success") is False
    assert "message" in empty_msg.get("error", "").lower()
    print(f"  [PASS] Empty message rejected: {empty_msg['error']}")

    # 4. Whitespace message
    ws_msg = show_desktop_notification(title="Valid title", message="   ")
    assert ws_msg.get("success") is False
    assert "message" in ws_msg.get("error", "").lower()
    print(f"  [PASS] Whitespace message rejected: {ws_msg['error']}")


async def test_tool_registry_auto_discovery():
    print("\n" + "=" * 60)
    print("[TEST 5] Tool Registry Auto-Discovery & Async Execution")
    print("=" * 60)

    reset_registry()
    reg = get_registry(auto_discover=True)

    tool_name = "show_desktop_notification"
    assert tool_name in reg, f"Tool '{tool_name}' not discovered in ToolRegistry"

    tool_obj = reg[tool_name]
    schema = tool_obj.to_dict()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == tool_name
    assert "description" in schema["function"]
    assert "parameters" in schema["function"]

    props = schema["function"]["parameters"].get("properties", {})
    assert "title" in props
    assert "message" in props
    assert "buttons" in props
    assert "dialogue" in props
    print(f"  [PASS] Tool '{tool_name}' auto-discovered with properties: {list(props.keys())}")

    # Asynchronous execution via registry
    exec_res = await reg.execute(
        "show_desktop_notification",
        {
            "title": "Registry Async Alert",
            "message": "Executed successfully via ToolRegistry.execute.",
        },
    )
    assert isinstance(exec_res, dict)
    assert exec_res.get("success") is True
    assert exec_res.get("dispatched") is True
    print(f"  [PASS] Asynchronous reg.execute('{tool_name}') succeeded: {exec_res.get('status')}")


def main():
    print("Starting Standalone Verification Test Suite for Windows Desktop Notifications (Step 30)...")
    t0 = time.time()

    test_standard_notification_dispatch()
    test_interactive_notification_buttons()
    test_notification_with_dialogue()
    test_error_handling()
    asyncio.run(test_tool_registry_auto_discovery())

    elapsed = round(time.time() - t0, 2)
    print("\n" + "=" * 60)
    print(f"ALL TESTS PASSED SUCCESSFULLY in {elapsed}s (Exit Code: 0)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
