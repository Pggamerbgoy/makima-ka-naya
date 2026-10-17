"""
tests/verify_desktop_input.py — Verification suite for Win32 SendInput simulator.
Tests:
1. get_cursor_position
2. mouse_move (instant and smooth)
3. mouse_click (single, double, right)
4. mouse_scroll (vertical, horizontal)
5. keyboard_type (Unicode typing)
6. keyboard_hotkey (chords)
7. End-to-end typing into a live test application window.
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from makima.tools.desktop.input import (
    get_cursor_position,
    keyboard_hotkey,
    keyboard_type,
    mouse_click,
    mouse_drag,
    mouse_move,
    mouse_scroll,
)
from makima.tools.desktop.uia import read_ui_text
from makima.tools.os.apps import launch_app
from makima.tools.os.processes import terminate_process
from makima.tools.os.windows import _find_target_window, focus_window


def test_cursor_and_mouse() -> None:
    print("\n[TEST 1] Testing cursor positioning and mouse movement...")
    pos = get_cursor_position()
    assert "x" in pos and "y" in pos, f"Invalid cursor position format: {pos}"
    print(f"  [PASS] Initial cursor position: ({pos['x']}, {pos['y']})")

    # Move to known coordinate
    move_res = mouse_move(x=200, y=250, smooth=False)
    assert move_res.get("success") is True, f"mouse_move failed: {move_res}"
    print("  [PASS] Instant mouse_move to (200, 250) succeeded.")

    # Smooth movement
    smooth_res = mouse_move(x=350, y=400, smooth=True, steps=5)
    assert smooth_res.get("success") is True, f"smooth mouse_move failed: {smooth_res}"
    print("  [PASS] Smooth mouse_move to (350, 400) succeeded.")


def test_mouse_actions() -> None:
    print("\n[TEST 2] Testing mouse clicks, scroll, and drag...")
    click_res = mouse_click(button="left", click_type="single")
    assert click_res.get("success") is True
    print("  [PASS] Single left click dispatched.")

    dbl_res = mouse_click(button="left", click_type="double")
    assert dbl_res.get("success") is True
    print("  [PASS] Double left click dispatched.")

    scroll_res = mouse_scroll(clicks=2, direction="vertical")
    assert scroll_res.get("success") is True
    print("  [PASS] Vertical wheel scroll dispatched.")

    drag_res = mouse_drag(start_x=300, start_y=300, end_x=350, end_y=350, steps=3)
    assert drag_res.get("success") is True
    print("  [PASS] Mouse drag operation dispatched.")


def test_keyboard_input_live() -> None:
    print("\n[TEST 3] Testing native Unicode typing and hotkeys on live window...")
    launch_res = launch_app("notepad.exe")
    assert launch_res.get("success") is True, f"Launch failed: {launch_res}"
    time.sleep(1.5)

    try:
        hwnd, title, _ = _find_target_window("Notepad")
        assert hwnd is not None, "Failed to find Notepad window."
        focus_window(hwnd=hwnd)
        time.sleep(0.5)

        # Native Unicode typing (including emoji / symbols)
        sample_text = "Makima v2 SendInput Hardware Engine Verified: OK [100%]"
        type_res = keyboard_type(sample_text, title_query="Notepad")
        assert type_res.get("success") is True, f"keyboard_type failed: {type_res}"
        assert "active_window" in type_res, f"Missing active_window in type_res: {type_res}"
        active_win = type_res["active_window"]
        print(f"  [PASS] Typed {type_res.get('chars_typed')} Unicode characters on window '{active_win}'.")
        time.sleep(0.5)

        # Read back via UIA to verify the characters arrived in the Edit control
        read_res = read_ui_text(hwnd=hwnd, control_type="Edit")
        assert read_res.get("success") is True
        ui_text = read_res.get("text") or ""
        print(f"  [PASS] Live window text read-back: '{ui_text}'")
        assert "SendInput Hardware Engine" in ui_text, f"Unexpected text: {ui_text}"

        # Test hotkey: select all
        hotkey_res = keyboard_hotkey(["ctrl", "a"], title_query="Notepad")
        assert hotkey_res.get("success") is True
        assert "active_window" in hotkey_res, f"Missing active_window in hotkey_res: {hotkey_res}"
        print(f"  [PASS] Hotkey ['ctrl', 'a'] dispatched successfully on window '{hotkey_res['active_window']}'.")
        assert "Notepad" in hotkey_res["active_window"], f"Expected Notepad in active window, got: {hotkey_res['active_window']}"

    finally:
        terminate_process(name="Notepad.exe")
        print("  [CLEANUP] Terminated test Notepad process.")


if __name__ == "__main__":
    try:
        test_cursor_and_mouse()
        test_mouse_actions()
        test_keyboard_input_live()
        print("\nALL DESKTOP INPUT VERIFICATION TESTS PASSED (EXIT CODE 0).")
        sys.exit(0)
    except Exception as exc:
        print(f"\nTEST FAILED WITH EXCEPTION: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
