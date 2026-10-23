"""
Makima v2 — Set-of-Marks (SoM) Visual Grounding Engine.
Architectural Pattern: Microsoft OmniParser / OSWorld-style Set-of-Marks.
Overlays high-contrast bounding boxes and numbered pill badges onto live
interactive controls (Buttons, Edits, Menus, Tabs), allowing Multimodal LLMs
to select targets unambiguously by mark ID without coordinate math.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from PIL import ImageDraw, ImageFont

from makima.tools.desktop.screen import _capture_hwnd_to_image, _get_capture_dir
from makima.tools.desktop.uia import inspect_app_ui
from makima.tools.os.windows import _find_target_window
from makima.tools.registry import tool

logger = logging.getLogger(__name__)

# Global cache holding the most recent Set-of-Marks grounding map
_LAST_SOM_CACHE: dict[int, dict[str, Any]] = {}

INTERACTIVE_CONTROL_TYPES = {
    "button",
    "menuitem",
    "edit",
    "document",
    "tabitem",
    "checkbox",
    "radiobutton",
    "combobox",
    "hyperlink",
    "listitem",
    "treeitem",
    "splitbutton",
}

# High-contrast color palette for Set-of-Marks badges
BADGE_COLORS = [
    "#FF0055",  # Vibrant Rose
    "#00CCFF",  # Bright Cyan
    "#FFCC00",  # Vivid Amber
    "#00FF66",  # Neon Green
    "#9933FF",  # Electric Violet
    "#FF6600",  # Blazing Orange
]


def get_last_som_marks() -> dict[int, dict[str, Any]]:
    """Retrieves the most recent Set-of-Marks grounding lookup table."""
    return dict(_LAST_SOM_CACHE)


@tool(
    name="annotate_window_som",
    description="Capture target window and overlay high-contrast Set-of-Marks (SoM) numbered badges (#1, #2, ...) on interactive controls. Returns marked image path and marks lookup table.",
    tags=["desktop", "vision", "som", "grounding"],
)
def annotate_window_som(
    title_query: str | None = None,
    hwnd: int | None = None,
    max_marks: int = 40,
) -> dict[str, Any]:
    """
    Annotates target window with numbered visual markers.

    Args:
        title_query: Substring or title of target window.
        hwnd: Specific HWND of window.
        max_marks: Maximum number of visual marks to annotate.

    Returns:
        Structured result with image_path, total_marks, and marks dictionary.
    """
    global _LAST_SOM_CACHE

    target_hwnd, title, err = _find_target_window(title_query=title_query, hwnd=hwnd)
    if target_hwnd is None or err:
        return {"success": False, "error": err or "Target window not found"}

    # 1. Capture clean image
    img, cap_err = _capture_hwnd_to_image(target_hwnd)
    if img is None or cap_err:
        return {"success": False, "hwnd": target_hwnd, "window_title": title, "error": cap_err}

    # 2. Inspect controls via zero-vision UIA
    ui_res = inspect_app_ui(hwnd=target_hwnd, max_elements=100)
    controls = ui_res.get("controls", [])

    # 3. Filter interactive controls
    interactive_items = []
    for c in controls:
        ctype = (c.get("control_type") or "").strip().lower()
        rect = c.get("rect", {})
        w, h = rect.get("width", 0), rect.get("height", 0)
        # Require positive dimensions and interactive type
        if w > 4 and h > 4 and ctype in INTERACTIVE_CONTROL_TYPES:
            interactive_items.append(c)

    # Window screen bounds for coordinate transformation
    import win32gui

    win_left, win_top, win_right, win_bottom = win32gui.GetWindowRect(target_hwnd)

    # 4. Draw Set-of-Marks badges onto image
    annotated = img.copy()
    draw = ImageDraw.Draw(annotated)

    marks_map: dict[int, dict[str, Any]] = {}
    mark_count = 0

    # Default fallback font
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for elem in interactive_items:
        if mark_count >= max_marks:
            break

        rect = elem.get("rect", {})
        # Translate screen coordinates to window-relative coordinates
        rx = rect["left"] - win_left
        ry = rect["top"] - win_top
        rw = rect["width"]
        rh = rect["height"]

        # Ensure within image bounds
        if rx < 0 or ry < 0 or rx + rw > img.width or ry + rh > img.height:
            continue

        mark_count += 1
        mark_id = mark_count
        color = BADGE_COLORS[(mark_id - 1) % len(BADGE_COLORS)]

        # Black out password fields on the screenshot for zero visual credential leakage
        is_pwd = bool(elem.get("is_password", False)) or (
            "password" in str(elem.get("control_type", "")).lower()
            or "password" in str(elem.get("name", "")).lower()
        )
        if is_pwd:
            draw.rectangle([rx, ry, rx + rw, ry + rh], fill="black")

        # Draw bounding outline
        draw.rectangle([rx, ry, rx + rw, ry + rh], outline=color, width=2)

        # Draw badge pill at top-left
        badge_text = f" {mark_id} "
        badge_w = max(18, len(badge_text) * 8)
        badge_h = 16

        bx1 = max(0, rx)
        by1 = max(0, ry - badge_h if ry >= badge_h else ry)
        bx2 = min(img.width, bx1 + badge_w)
        by2 = min(img.height, by1 + badge_h)

        draw.rectangle([bx1, by1, bx2, by2], fill=color)
        draw.text((bx1 + 2, by1 + 2), badge_text, fill="black", font=font)

        # Physical screen center coordinates for clicking
        screen_cx = rect["left"] + rw // 2
        screen_cy = rect["top"] + rh // 2

        marks_map[mark_id] = {
            "mark_id": mark_id,
            "name": elem.get("name", ""),
            "control_type": elem.get("control_type", ""),
            "automation_id": elem.get("automation_id", ""),
            "center": [screen_cx, screen_cy],
            "window_center": [rx + rw // 2, ry + rh // 2],
            "rect": rect,
        }

    # 5. Save annotated image
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_title = "".join(c if c.isalnum() else "_" for c in title[:20])
    out_path = _get_capture_dir() / f"som_{safe_title}_{ts}.png"
    annotated.save(str(out_path), format="PNG")

    # Update global cache
    _LAST_SOM_CACHE = marks_map

    return {
        "success": True,
        "hwnd": target_hwnd,
        "window_title": title,
        "image_path": str(out_path),
        "total_marks": len(marks_map),
        "marks": marks_map,
    }
