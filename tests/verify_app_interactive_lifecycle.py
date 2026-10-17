"""
Makima v2 — End-to-End Interactive Desktop App Lifecycle Verification.
Test Flow:
1. Create a dedicated test file on disk.
2. Launch the application (Notepad) with the target file.
3. Discover and inspect the application UI tree using zero-vision UIA.
4. Perform interactive work inside the application (set text inside the Edit control).
5. Read back the live UI state and verify that the UI reflects the modified content.
6. Trigger the application save command (persisting UI work to disk).
7. Cleanly terminate the application process.
8. Read the file from disk and assert that the interactive work was saved.
9. Dispatch a desktop notification confirming test completion.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import win32con
import win32gui

from makima.tools.desktop.uia import (
    inspect_app_ui,
    read_ui_text,
    set_ui_text,
)
from makima.tools.os.apps import launch_app
from makima.tools.os.notifications import show_desktop_notification
from makima.tools.os.processes import terminate_process
from makima.tools.os.windows import _find_target_window, list_open_windows


def test_interactive_notepad_lifecycle() -> None:
    print("\n============================================================")
    print(">>> STARTING INTERACTIVE APPLICATION LIFECYCLE TEST (NOTEPAD)")
    print("============================================================")

    # 1. Prepare test file on disk
    test_file = pathlib.Path("tests_scratch_interactive_doc.txt").resolve()
    initial_text = f"Baseline file created at {datetime.datetime.now().isoformat()}\n"
    test_file.write_text(initial_text, encoding="utf-8")
    print(f"[1/8] Test file prepared: {test_file}")

    try:
        # 2. Launch application with target file
        launch_res = launch_app("notepad.exe", args=[str(test_file)])
        print(f"[2/8] Launch outcome: success={launch_res.get('success')}, PID={launch_res.get('pid')}")
        assert launch_res.get("success"), f"Launch failed: {launch_res}"
        target_pid = launch_res.get("pid")

        # Give window a moment to initialize
        time.sleep(2.0)

        # 3. Locate window handle and inspect UI controls
        hwnd, win_title, err = _find_target_window(title_query="tests_scratch_interactive_doc")
        if not hwnd:
            # Fallback title query for notepad
            hwnd, win_title, err = _find_target_window(title_query="Notepad")

        print(f"[3/8] Target window located: HWND={hwnd}, Title='{win_title}', err={err}")
        assert hwnd is not None, "Failed to find active Notepad window handle."

        ui_tree = inspect_app_ui(hwnd=hwnd, max_elements=20)
        print(f"      UI Inspection: success={ui_tree.get('success')}, controls_found={ui_tree.get('total_controls_found')}")
        assert ui_tree.get("success"), f"UI inspection failed: {ui_tree}"

        # 4. Perform interactive work inside the application (write text)
        work_content = (
            f"=== MAKIMA V2 INTERACTIVE AUTOMATION ===\n"
            f"Work performed at: {datetime.datetime.now().isoformat()}\n"
            f"Zero-Vision UI Automation: ACTIVE\n"
            f"Status: ALL TESTS PASSED\n"
            f"========================================"
        )
        set_res = set_ui_text(
            hwnd=hwnd,
            control_type="Edit",
            text=work_content,
            clear_first=True,
        )
        print(f"[4/8] Interactive UI text set: success={set_res.get('success')}")
        assert set_res.get("success"), f"set_ui_text failed: {set_res}"

        # 5. Read back text from the live UI to verify real-time state
        read_res = read_ui_text(hwnd=hwnd, control_type="Edit")
        read_text = (read_res.get("text") or "").strip()
        print(f"[5/8] Live UI read-back: success={read_res.get('success')}")
        print(f"      Read text length: {len(read_text)} chars")
        assert read_res.get("success"), f"read_ui_text failed: {read_res}"
        assert "MAKIMA V2 INTERACTIVE AUTOMATION" in read_text, f"UI text mismatch: {read_text}"

        # 6. Save work to disk via application Save command
        print("[6/8] Triggering application Save command...")
        # Win32 WM_COMMAND ID 3 is standard File -> Save in Notepad
        win32gui.SendMessage(hwnd, win32con.WM_COMMAND, 3, 0)
        time.sleep(1.0)

        # 7. Cleanly close application
        print("[7/8] Terminating application cleanly...")
        # Close window politely first
        win32gui.SendMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(0.5)

        # Ensure process terminated
        terminate_res = terminate_process(name="notepad.exe")
        print(f"      Process termination outcome: {terminate_res.get('success')}, killed={terminate_res.get('terminated_count')}")

        # 8. Verify disk persistence
        disk_content = test_file.read_text(encoding="utf-8").strip()
        print("[8/8] Verifying saved file content on disk:")
        print("------------------------------------------------------------")
        print(disk_content)
        print("------------------------------------------------------------")
        assert "MAKIMA V2 INTERACTIVE AUTOMATION" in disk_content, "Work was NOT saved to disk!"
        assert "Status: ALL TESTS PASSED" in disk_content, "Expected content missing from saved disk file!"
        print(">>> SUCCESS: Interactive work inside application was verified on disk!")

        # 9. Send desktop notification
        notif_res = show_desktop_notification(
            title="Makima Interactive Test",
            message="End-to-end interactive desktop application test PASSED!",
        )
        print(f">>> Desktop notification dispatched: success={notif_res.get('success')}")

    finally:
        # Cleanup test file
        if test_file.exists():
            try:
                test_file.unlink()
                print(f"[CLEANUP] Removed test scratch file: {test_file}")
            except Exception as e:
                print(f"[CLEANUP WARNING] Could not remove test file: {e}")

        # Ensure any leftover notepad instances are cleaned up
        terminate_process(name="notepad.exe")


if __name__ == "__main__":
    try:
        test_interactive_notepad_lifecycle()
        print("\nALL INTERACTIVE LIFECYCLE TESTS COMPLETED WITH EXIT CODE 0.")
        sys.exit(0)
    except Exception as exc:
        print(f"\nTEST SUITE FAILED WITH EXCEPTION: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
