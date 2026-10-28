"""
Makima v2 — Unified SOTA Computer Use Facade.
Architectural Pattern: Anthropic Computer Use & OSWorld-compatible unified action space.
Integrates hardware-grade SendInput, zero-vision UIA fast-path, and Set-of-Marks visual
grounding into a single tool invocation endpoint for autonomous GUI agents.
"""

from __future__ import annotations

import logging
from typing import Any

from makima.tools.desktop.input import (
    get_cursor_position,
    keyboard_hotkey,
    keyboard_type,
    mouse_click,
    mouse_drag,
    mouse_move,
    mouse_scroll,
)
from makima.tools.desktop.screen import capture_screen, capture_window
from makima.tools.desktop.som import annotate_window_som, get_last_som_marks
from makima.tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="computer_use",
    description=(
        "High-level native desktop UI action using coordinates or Set-of-Marks IDs. Supports click, move, drag, type, "
        "hotkey, scroll, screenshot, and visual grounding in one call."
    ),
    tags=["desktop", "computer_use", "automation", "gui", "vision"],
    purpose="Perform one concrete mouse/keyboard/screenshot action in a native desktop interface.",
    capabilities=[
        "Act on a physical desktop using screen coordinates or recent Set-of-Marks IDs.",
        "Capture a screen/window or annotate controls before choosing a visual target.",
        "Type text or send keyboard shortcuts to the foreground desktop application.",
    ],
    use_when=[
        "The requested action targets native desktop UI and the target is identified visually by coordinates or a recent mark ID.",
        "A screenshot or visual mark annotation is needed to locate the next UI action.",
    ],
    avoid_when=[
        "The target is a web page in the persistent browser; use browser_interact.",
        "A native application exposes a named UIA control that can be addressed semantically; prefer the UI Automation tools.",
        "The user asks to launch/close an app, control media playback, or change system volume rather than interact with UI controls.",
    ],
    examples=[
        "Click the visible button at a supplied coordinate.",
        "Capture a screenshot and click a recent Set-of-Marks ID.",
        "Type text into the currently focused native application.",
    ],
    side_effect="Sends real mouse/keyboard input or captures the desktop; actions may change application state.",
)
def computer_use(
    action: str,
    coordinate: list[int] | None = None,
    mark_id: int | None = None,
    text: str | None = None,
    key: str | None = None,
    keys: list[str] | None = None,
    button: str = "left",
    click_type: str = "single",
    clicks: int = 1,
    direction: str = "vertical",
    title_query: str | None = None,
    hwnd: int | None = None,
    auto_observe: bool = True,
) -> dict[str, Any]:
    """
    Executes a computer control action.

    Args:
        action: 'click', 'double_click', 'right_click', 'middle_click', 'mouse_move',
                'drag', 'type', 'key', 'hotkey', 'scroll', 'screenshot', 'som', 'cursor_position'.
        coordinate: [x, y] screen coordinates for click/move/drag.
        mark_id: Numeric Set-of-Marks badge ID (e.g. 1, 2) to target visually without coordinates.
        text: String of text to type for 'type' action.
        key: Single key to press for 'key' action (e.g. 'enter', 'esc').
        keys: List of keys for 'hotkey' chord (e.g. ['ctrl', 's']).
        button: Mouse button ('left', 'right', 'middle').
        click_type: 'single', 'double', 'triple'.
        clicks: Scroll clicks count or repetition count.
        direction: 'vertical' or 'horizontal' for scrolling.
        title_query: Optional window title to target.
        hwnd: Optional window HWND to target.
    """
    act = (action or "").strip().lower()

    # 1. Resolve coordinates from mark_id if provided
    resolved_coord: list[int] | None = None
    target_mark_info: dict[str, Any] | None = None
    if mark_id is not None:
        marks = get_last_som_marks()
        if mark_id in marks:
            target_mark_info = marks[mark_id]
            resolved_coord = target_mark_info.get("center")
        else:
            return {
                "success": False,
                "error": f"Mark ID #{mark_id} not found in recent Set-of-Marks cache. Call action='som' first.",
            }
    elif coordinate and len(coordinate) >= 2:
        resolved_coord = [int(coordinate[0]), int(coordinate[1])]

    # 2. Action dispatch table

    # Clicks
    if act in ("click", "left_click"):
        x = resolved_coord[0] if resolved_coord else None
        y = resolved_coord[1] if resolved_coord else None
        res = mouse_click(x=x, y=y, button=button, click_type=click_type)
        if target_mark_info:
            res["target_mark"] = target_mark_info
        return res

    elif act == "double_click":
        x = resolved_coord[0] if resolved_coord else None
        y = resolved_coord[1] if resolved_coord else None
        res = mouse_click(x=x, y=y, button=button, click_type="double")
        if target_mark_info:
            res["target_mark"] = target_mark_info
        return res

    elif act == "right_click":
        x = resolved_coord[0] if resolved_coord else None
        y = resolved_coord[1] if resolved_coord else None
        res = mouse_click(x=x, y=y, button="right", click_type="single")
        if target_mark_info:
            res["target_mark"] = target_mark_info
        return res

    elif act == "middle_click":
        x = resolved_coord[0] if resolved_coord else None
        y = resolved_coord[1] if resolved_coord else None
        res = mouse_click(x=x, y=y, button="middle", click_type="single")
        if target_mark_info:
            res["target_mark"] = target_mark_info
        return res

    # Motion
    elif act == "mouse_move":
        if not resolved_coord:
            return {"success": False, "error": "Action 'mouse_move' requires 'coordinate' or 'mark_id'."}
        return mouse_move(x=resolved_coord[0], y=resolved_coord[1], smooth=True)

    elif act == "drag":
        curr = get_cursor_position()
        if not resolved_coord:
            return {"success": False, "error": "Action 'drag' requires target 'coordinate' or 'mark_id'."}
        return mouse_drag(
            start_x=curr["x"],
            start_y=curr["y"],
            end_x=resolved_coord[0],
            end_y=resolved_coord[1],
            button=button,
        )

    # Keyboard
    elif act in ("type", "type_text"):
        if text is None:
            return {"success": False, "error": "Action 'type' requires 'text' parameter."}
        return keyboard_type(text=text, title_query=title_query, hwnd=hwnd)

    elif act in ("key", "press_key"):
        target_key = key or (keys[0] if keys else None)
        if not target_key:
            return {"success": False, "error": "Action 'key' requires 'key' parameter."}
        return keyboard_hotkey(keys=[target_key])

    elif act == "hotkey":
        target_keys = keys or ([key] if key else None)
        if not target_keys:
            return {"success": False, "error": "Action 'hotkey' requires 'keys' list parameter."}
        return keyboard_hotkey(keys=target_keys)

    # Scrolling
    elif act in ("scroll", "mouse_scroll"):
        return mouse_scroll(clicks=clicks, direction=direction)

    # Visual Observation & Grounding
    elif act in ("screenshot", "capture"):
        if title_query or hwnd:
            return capture_window(title_query=title_query, hwnd=hwnd)
        return capture_screen()

    elif act in ("som", "set_of_marks", "annotate"):
        return annotate_window_som(title_query=title_query, hwnd=hwnd)

    elif act == "cursor_position":
        return get_cursor_position()

    else:
        return {
            "success": False,
            "error": f"Unknown computer_use action: '{action}'. Supported: click, double_click, right_click, middle_click, mouse_move, drag, type, key, hotkey, scroll, screenshot, som, cursor_position.",
        }
