"""
tests/verify_computer_use.py — End-to-end verification of unified computer_use facade.
Tests:
1. computer_use(action='screenshot')
2. computer_use(action='som') (Set-of-Marks grounding)
3. computer_use(action='click', mark_id=...)
4. computer_use(action='type', text=...)
5. computer_use(action='hotkey', keys=...)
6. computer_use(action='scroll')
7. computer_use(action='cursor_position')
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from makima.tools.desktop.computer_use import computer_use
from makima.tools.desktop.uia import read_ui_text
from makima.tools.os.apps import launch_app
from makima.tools.os.processes import terminate_process
from makima.tools.os.windows import _find_target_window


def test_unified_computer_use() -> None:
    print("\n============================================================")
    print(">>> STARTING UNIFIED COMPUTER USE (ASTRA-GRADE) TEST SUITE")
    print("============================================================")

    launch_res = launch_app("notepad.exe")
    assert launch_res.get("success") is True
    print(f"[1/8] Notepad launched (PID: {launch_res.get('pid')})")
    time.sleep(1.5)

    created_images = []

    try:
        hwnd, title, _ = _find_target_window("Notepad")
        assert hwnd is not None, "Failed locating Notepad window."

        # 1. Screenshot action
        shot_res = computer_use(action="screenshot", hwnd=hwnd)
        assert shot_res.get("success") is True
        created_images.append(pathlib.Path(shot_res["image_path"]))
        print(f"[2/8] computer_use(action='screenshot') PASS: {shot_res['width']}x{shot_res['height']}")

        # 2. Set-of-Marks visual grounding
        som_res = computer_use(action="som", hwnd=hwnd)
        assert som_res.get("success") is True
        created_images.append(pathlib.Path(som_res["image_path"]))
        total_marks = som_res.get("total_marks", 0)
        assert total_marks > 0
        print(f"[3/8] computer_use(action='som') PASS: {total_marks} visual marks generated")

        # 3. Mark-based clicking (Click Mark #1)
        click_res = computer_use(action="click", mark_id=1)
        assert click_res.get("success") is True
        print(f"[4/8] computer_use(action='click', mark_id=1) PASS: clicked {click_res.get('target_mark', {}).get('name')}")

        # 4. Typing action
        sample_text = "Makima v2 Astra-Grade PC Control Verified!"
        type_res = computer_use(action="type", text=sample_text, title_query="Notepad")
        assert type_res.get("success") is True
        print(f"[5/8] computer_use(action='type') PASS: typed {type_res.get('chars_typed')} chars")
        time.sleep(0.5)

        # 5. Hotkey chord action
        hotkey_res = computer_use(action="hotkey", keys=["ctrl", "a"])
        assert hotkey_res.get("success") is True
        print("[6/8] computer_use(action='hotkey', keys=['ctrl', 'a']) PASS")

        # 6. Scroll action
        scroll_res = computer_use(action="scroll", clicks=2, direction="vertical")
        assert scroll_res.get("success") is True
        print("[7/8] computer_use(action='scroll') PASS")

        # 7. Cursor position query
        cur_pos = computer_use(action="cursor_position")
        assert "x" in cur_pos and "y" in cur_pos
        print(f"[8/8] computer_use(action='cursor_position') PASS: pos=({cur_pos['x']}, {cur_pos['y']})")

        # 8. Assert UI text readback
        read_res = read_ui_text(hwnd=hwnd, control_type="Edit")
        ui_text = read_res.get("text") or ""
        assert "Astra-Grade PC Control" in ui_text, f"Typed text mismatch: '{ui_text}'"
        print(f">>> UI verification confirmed: '{ui_text}'")

    finally:
        terminate_process(name="Notepad.exe")
        print("[CLEANUP] Terminated test Notepad process.")
        for p in created_images:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        print(f"[CLEANUP] Removed {len(created_images)} test capture images.")


if __name__ == "__main__":
    try:
        test_unified_computer_use()
        print("\nALL UNIFIED COMPUTER USE TESTS COMPLETED WITH EXIT CODE 0.")
        sys.exit(0)
    except Exception as exc:
        print(f"\nTEST FAILED WITH EXCEPTION: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
