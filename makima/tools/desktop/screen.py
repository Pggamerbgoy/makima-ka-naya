"""
Makima v2 — High-Performance Desktop Screen & Window Capture Engine.
Architectural Pattern: Win32 GDI + PrintWindow (PW_RENDERFULLCONTENT).
Captures exact high-resolution bitmaps of target application windows even when
occluded or layered, producing clean PNG images for Multimodal Vision LLMs.
"""

from __future__ import annotations

import ctypes
import datetime
import logging
from pathlib import Path
from typing import Any

import win32gui
import win32ui
from PIL import Image

from makima.config import get_settings
from makima.tools.os.windows import _find_target_window
from makima.tools.registry import tool

logger = logging.getLogger(__name__)

PW_RENDERFULLCONTENT = 2


def _get_capture_dir() -> Path:
    """Returns directory for persisting screen captures."""
    try:
        settings = get_settings()
        cap_dir = settings.data_dir_path / "captures"
    except Exception:
        cap_dir = Path.home() / ".makima" / "captures"
    cap_dir.mkdir(parents=True, exist_ok=True)
    return cap_dir


def _capture_hwnd_to_image(hwnd: int) -> tuple[Image.Image | None, str | None]:
    """Captures a window handle's visual content into a PIL Image via PrintWindow."""
    if not win32gui.IsWindow(hwnd):
        return None, f"Invalid window handle (HWND: {hwnd})"

    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = max(1, right - left)
        height = max(1, bottom - top)

        hwndDC = win32gui.GetWindowDC(hwnd)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()

        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
        saveDC.SelectObject(saveBitMap)

        # PrintWindow PW_RENDERFULLCONTENT (2)
        res = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), PW_RENDERFULLCONTENT)
        if res == 0:
            # Fallback to standard PrintWindow (0)
            res = ctypes.windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 0)

        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB",
            (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr,
            "raw",
            "BGRX",
            0,
            1,
        )

        # Cleanup GDI resources
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)

        return img, None
    except Exception as exc:
        logger.exception("Failed capturing HWND %s: %s", hwnd, exc)
        return None, str(exc)


@tool(
    name="capture_window",
    description="Capture a high-resolution screenshot of a target application window by title or HWND. Returns image path, dimensions, and window coordinates.",
    tags=["desktop", "vision", "screenshot"],
)
def capture_window(
    title_query: str | None = None,
    hwnd: int | None = None,
    save_path: str | None = None,
) -> dict[str, Any]:
    """
    Captures target window screenshot.

    Args:
        title_query: Substring or title of target application window.
        hwnd: Specific HWND of window.
        save_path: Optional explicit file path to save PNG. If None, saves to ~/.makima/captures/.
    """
    target_hwnd, title, err = _find_target_window(title_query=title_query, hwnd=hwnd)
    if target_hwnd is None or err:
        return {"success": False, "error": err or "Target window not found"}

    img, cap_err = _capture_hwnd_to_image(target_hwnd)
    if img is None or cap_err:
        return {"success": False, "hwnd": target_hwnd, "window_title": title, "error": cap_err}

    # Determine save destination
    if save_path:
        out_path = Path(save_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_title = "".join(c if c.isalnum() else "_" for c in title[:20])
        out_path = _get_capture_dir() / f"window_{safe_title}_{ts}.png"

    img.save(str(out_path), format="PNG")

    left, top, right, bottom = win32gui.GetWindowRect(target_hwnd)
    return {
        "success": True,
        "hwnd": target_hwnd,
        "window_title": title,
        "image_path": str(out_path),
        "width": img.width,
        "height": img.height,
        "rect": {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": right - left,
            "height": bottom - top,
        },
    }


@tool(
    name="capture_screen",
    description="Capture a screenshot of the active foreground window or primary desktop interface.",
    tags=["desktop", "vision", "screenshot"],
)
def capture_screen(
    save_path: str | None = None,
) -> dict[str, Any]:
    """Captures the active foreground window as primary screen observation."""
    fg_hwnd = win32gui.GetForegroundWindow()
    if fg_hwnd and win32gui.IsWindow(fg_hwnd) and win32gui.IsWindowVisible(fg_hwnd):
        title = win32gui.GetWindowText(fg_hwnd).strip()
        if title:
            return capture_window(hwnd=fg_hwnd, save_path=save_path)

    # Fallback to the topmost visible desktop window
    try:
        from makima.tools.os.windows import list_open_windows
        open_wins = list_open_windows()
        for w in open_wins:
            whwnd = w.get("hwnd")
            if whwnd and win32gui.IsWindow(whwnd):
                return capture_window(hwnd=whwnd, save_path=save_path)
    except Exception as exc:
        logger.debug("capture_screen fallback notice: %s", exc)

    return {"success": False, "error": "No active or visible window found to capture"}
