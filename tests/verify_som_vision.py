"""
tests/verify_som_vision.py — Verification suite for Window Capture and Set-of-Marks (SoM) Grounding.
Tests:
1. capture_window on live application (Notepad).
2. capture_screen on foreground application.
3. annotate_window_som (Set-of-Marks visual badge overlay).
4. Assert generated marks dictionary structure and coordinate mapping.
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from makima.tools.desktop.screen import capture_screen, capture_window
from makima.tools.desktop.som import annotate_window_som, get_last_som_marks
from makima.tools.os.apps import launch_app
from makima.tools.os.processes import terminate_process
from makima.tools.os.windows import _find_target_window


def test_vision_and_som_lifecycle() -> None:
    print("\n============================================================")
    print(">>> STARTING VISION & SET-OF-MARKS (SOM) VERIFICATION SUITE")
    print("============================================================")

    # 1. Launch live application
    launch_res = launch_app("notepad.exe")
    assert launch_res.get("success") is True, f"Failed launching Notepad: {launch_res}"
    print(f"[1/5] Notepad launched (PID: {launch_res.get('pid')})")
    time.sleep(1.5)

    created_images = []

    try:
        hwnd, title, _ = _find_target_window("Notepad")
        assert hwnd is not None, "Failed to locate Notepad window handle."
        print(f"[2/5] Window located: HWND={hwnd}, Title='{title}'")

        # 2. Test clean window capture
        cap_res = capture_window(hwnd=hwnd)
        assert cap_res.get("success") is True, f"capture_window failed: {cap_res}"
        img_path = pathlib.Path(cap_res["image_path"])
        created_images.append(img_path)
        assert img_path.exists() and img_path.stat().st_size > 0
        print(f"[3/5] capture_window PASS: size={cap_res['width']}x{cap_res['height']}, file={img_path.name}")

        # 3. Test Set-of-Marks (SoM) annotation
        som_res = annotate_window_som(hwnd=hwnd, max_marks=20)
        assert som_res.get("success") is True, f"annotate_window_som failed: {som_res}"
        som_path = pathlib.Path(som_res["image_path"])
        created_images.append(som_path)
        assert som_path.exists() and som_path.stat().st_size > 0
        total_marks = som_res.get("total_marks", 0)
        print(f"[4/5] annotate_window_som PASS: total_marks={total_marks}, file={som_path.name}")
        assert total_marks > 0, "No interactive controls were marked!"

        # Inspect marks dictionary
        marks = som_res.get("marks", {})
        print("      Sample detected Set-of-Marks badges:")
        for mid in list(marks.keys())[:5]:
            m = marks[mid]
            print(f"        Tag #{mid}: type={m.get('control_type')} | name='{m.get('name')}' | screen_center={m.get('center')}")
            assert "center" in m and len(m["center"]) == 2
            assert "rect" in m

        # Verify global cache
        cached_marks = get_last_som_marks()
        assert len(cached_marks) == total_marks, "Cached marks count mismatch!"

        # 4. Test capture_screen
        scr_res = capture_screen()
        assert scr_res.get("success") is True, f"capture_screen failed: {scr_res}"
        scr_path = pathlib.Path(scr_res["image_path"])
        created_images.append(scr_path)
        assert scr_path.exists()
        print(f"[5/5] capture_screen PASS: file={scr_path.name}")

    finally:
        # Clean up process
        terminate_process(name="Notepad.exe")
        print("[CLEANUP] Terminated test Notepad process.")

        # Clean up test screenshots
        for p in created_images:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        print(f"[CLEANUP] Purged {len(created_images)} temporary test images.")


if __name__ == "__main__":
    try:
        test_vision_and_som_lifecycle()
        print("\nALL VISION & SET-OF-MARKS TESTS COMPLETED WITH EXIT CODE 0.")
        sys.exit(0)
    except Exception as exc:
        print(f"\nTEST FAILED WITH EXCEPTION: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
