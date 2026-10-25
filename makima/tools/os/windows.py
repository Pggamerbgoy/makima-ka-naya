"""
Makima v2 — Windows GUI & Window Management Tools.
Architectural Pattern: Modular, library-first window control using pywin32 directly.
Zero-Hardcoding Guarantee: Fully dynamic window discovery, placement introspection, and focus handling.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Dict, Iterator, List, Optional, Tuple

import ctypes
import psutil
import win32api
import win32con
import win32gui
import win32process
import win32service

from makima.tools.registry import tool

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _open_interactive_desktop() -> Iterator[Any]:
    """
    Context manager that acquires and keeps open the 'default' interactive desktop handle.
    Windows Win32 API requires an active desktop handle to inspect and manipulate foreign windows
    across different execution contexts and sessions.
    """
    desk = None
    try:
        desk = win32service.OpenDesktop("default", 0, False, win32con.GENERIC_ALL)
    except Exception as exc:
        logger.debug("Could not open 'default' desktop with GENERIC_ALL: %s", exc)
        try:
            desk = win32service.OpenDesktop("default", 0, False, win32con.GENERIC_READ)
        except Exception as exc2:
            logger.debug("Could not open 'default' desktop with GENERIC_READ: %s", exc2)

    try:
        if desk is not None:
            try:
                desk.SetThreadDesktop()
            except Exception as desk_exc:
                logger.debug("SetThreadDesktop notice: %s", desk_exc)
        yield desk
    finally:
        desk = None


def _enumerate_window_handles(desk: Any = None) -> List[int]:
    """
    Enumerate all top-level window handles across interactive desktop and thread desktop.
    """
    hwnds: List[int] = []
    seen: set[int] = set()

    # 1. Primary: default interactive desktop
    if desk is not None:
        try:
            for h in desk.EnumDesktopWindows():
                ih = int(h)
                if ih not in seen:
                    seen.add(ih)
                    hwnds.append(ih)
        except Exception as exc:
            logger.debug("EnumDesktopWindows failed: %s", exc)

    # 2. Secondary fallback / supplement: thread window station
    def _enum_cb(hwnd: int, extra: Any) -> bool:
        ih = int(hwnd)
        if ih not in seen:
            seen.add(ih)
            hwnds.append(ih)
        return True

    try:
        win32gui.EnumWindows(_enum_cb, None)
    except Exception as exc:
        logger.debug("EnumWindows completed with notice: %s", exc)

    return hwnds


def _resolve_window_state(hwnd: int) -> str:
    """Determine whether a window is minimized, maximized, or normal."""
    try:
        if win32gui.IsIconic(hwnd):
            return "minimized"
        placement = win32gui.GetWindowPlacement(hwnd)
        if placement[1] == win32con.SW_SHOWMAXIMIZED:
            return "maximized"
        return "normal"
    except Exception:
        return "normal"


def _resolve_window_rect(hwnd: int) -> Dict[str, int]:
    """Retrieve window bounding box coordinates and dimensions."""
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": max(0, right - left),
            "height": max(0, bottom - top),
        }
    except Exception:
        return {"left": 0, "top": 0, "right": 0, "bottom": 0, "width": 0, "height": 0}


def _find_target_window(
    title_query: Optional[str] = None,
    hwnd: Optional[int] = None,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Resolves a target window by HWND or title query string.
    Returns (hwnd, title, error_message).
    """
    if hwnd is not None:
        if not win32gui.IsWindow(hwnd):
            return None, None, f"Invalid window handle (HWND: {hwnd}). Window does not exist."
        title = win32gui.GetWindowText(hwnd).strip()
        return hwnd, title, None

    if not title_query:
        return None, None, "Either 'hwnd' or 'title_query' must be provided."

    all_windows = list_open_windows()
    query = title_query.strip().lower()

    # Pass 1: Exact title match
    for w in all_windows:
        if w["title"].strip().lower() == query:
            return w["hwnd"], w["title"], None

    # Pass 2: Title substring match
    for w in all_windows:
        if query in w["title"].strip().lower():
            return w["hwnd"], w["title"], None

    # Pass 3: Process name match
    for w in all_windows:
        if query in (w.get("process_name") or "").strip().lower():
            return w["hwnd"], w["title"], None

    return None, None, f"No open window found matching title query '{title_query}'."


@tool(
    name="list_open_windows",
    description="List all active, visible top-level windows with handles, titles, PIDs, and positions.",
    tags=["os", "windows", "gui"],
)
def list_open_windows() -> List[Dict[str, Any]]:
    """
    List all open, visible desktop windows with details.

    Returns:
        List of dictionaries with window details:
        hwnd, title, pid, process_name, state (normal/minimized/maximized), rect (left, top, right, bottom, width, height).
    """
    windows: List[Dict[str, Any]] = []

    with _open_interactive_desktop() as desk:
        handles = _enumerate_window_handles(desk)

        for hwnd in handles:
            try:
                if not win32gui.IsWindow(hwnd):
                    continue
                if not win32gui.IsWindowVisible(hwnd):
                    continue

                title = win32gui.GetWindowText(hwnd).strip()
                if not title:
                    continue

                # Process association
                pid = 0
                process_name = "unknown"
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if pid > 0:
                        process_name = psutil.Process(pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                    pass

                state = _resolve_window_state(hwnd)
                rect = _resolve_window_rect(hwnd)

                windows.append(
                    {
                        "hwnd": int(hwnd),
                        "title": title,
                        "pid": pid,
                        "process_name": process_name,
                        "state": state,
                        "rect": rect,
                    }
                )
            except Exception as exc:
                logger.debug("Error processing window %s: %s", hwnd, exc)
                continue

    return windows


@tool(
    name="focus_window",
    description="Bring a target window into the foreground and restore focus by title or HWND.",
    tags=["os", "windows", "gui"],
    purpose="Focus a desktop window without closing or terminating it.",
    capabilities=[
        "Find a window by title query or handle.",
        "Restore and bring the target window to the foreground.",
    ],
    use_when=[
        "The user wants to switch to or focus an existing window.",
    ],
    avoid_when=[
        "The user wants the application to close or the process to terminate.",
        "The user wants only media playback to stop or pause.",
    ],
    examples=[
        "Bring an existing application window to the foreground.",
    ],
    side_effect="Changes window focus and visibility state; does not terminate the target application.",
)
def focus_window(
    title_query: Optional[str] = None,
    hwnd: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Focus and activate a window, restoring it if minimized.

    Args:
        title_query: Substring or full title of window to focus.
        hwnd: Specific window handle (HWND) to focus.

    Returns:
        Dictionary indicating operation success, HWND, and window title.
    """
    with _open_interactive_desktop():
        target_hwnd, title, err = _find_target_window(title_query=title_query, hwnd=hwnd)
        if target_hwnd is None or err:
            return {"success": False, "error": err}

        try:
            user32 = ctypes.windll.user32

            # Restore if minimized
            if win32gui.IsIconic(target_hwnd):
                win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)

            # Unlock foreground rights across threads
            fg_hwnd = user32.GetForegroundWindow()
            fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
            cur_thread = win32api.GetCurrentThreadId()

            if fg_thread and fg_thread != cur_thread:
                try:
                    user32.AttachThreadInput(cur_thread, fg_thread, True)
                except Exception:
                    pass

            try:
                win32gui.ShowWindow(target_hwnd, win32con.SW_SHOW)
                win32gui.BringWindowToTop(target_hwnd)
                win32gui.SetForegroundWindow(target_hwnd)
            except Exception as fg_exc:
                logger.debug("Win32 BringWindowToTop/SetForegroundWindow notice: %s", fg_exc)
            finally:
                if fg_thread and fg_thread != cur_thread:
                    try:
                        user32.AttachThreadInput(cur_thread, fg_thread, False)
                    except Exception:
                        pass

            return {
                "success": True,
                "hwnd": target_hwnd,
                "title": title,
                "action": "focused",
                "message": f"Successfully focused window '{title}' (HWND: {target_hwnd}).",
            }
        except Exception as exc:
            logger.exception("Failed to focus window %s: %s", target_hwnd, exc)
            return {
                "success": False,
                "hwnd": target_hwnd,
                "title": title,
                "error": f"Failed to focus window: {exc}",
            }


@tool(
    name="minimize_window",
    description="Minimize a target window to the taskbar by title or HWND.",
    tags=["os", "windows", "gui"],
)
def minimize_window(
    title_query: Optional[str] = None,
    hwnd: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Minimize a window to the taskbar.

    Args:
        title_query: Substring or full title of window to minimize.
        hwnd: Specific window handle (HWND) to minimize.

    Returns:
        Dictionary indicating operation success, HWND, and window title.
    """
    with _open_interactive_desktop():
        target_hwnd, title, err = _find_target_window(title_query=title_query, hwnd=hwnd)
        if target_hwnd is None or err:
            return {"success": False, "error": err}

        try:
            win32gui.ShowWindow(target_hwnd, win32con.SW_MINIMIZE)
            return {
                "success": True,
                "hwnd": target_hwnd,
                "title": title,
                "action": "minimized",
                "message": f"Successfully minimized window '{title}' (HWND: {target_hwnd}).",
            }
        except Exception as exc:
            logger.exception("Failed to minimize window %s: %s", target_hwnd, exc)
            return {
                "success": False,
                "hwnd": target_hwnd,
                "title": title,
                "error": f"Failed to minimize window: {exc}",
            }


@tool(
    name="maximize_window",
    description="Maximize a target window to fill the display by title or HWND.",
    tags=["os", "windows", "gui"],
)
def maximize_window(
    title_query: Optional[str] = None,
    hwnd: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Maximize a window.

    Args:
        title_query: Substring or full title of window to maximize.
        hwnd: Specific window handle (HWND) to maximize.

    Returns:
        Dictionary indicating operation success, HWND, and window title.
    """
    with _open_interactive_desktop():
        target_hwnd, title, err = _find_target_window(title_query=title_query, hwnd=hwnd)
        if target_hwnd is None or err:
            return {"success": False, "error": err}

        try:
            win32gui.ShowWindow(target_hwnd, win32con.SW_MAXIMIZE)
            return {
                "success": True,
                "hwnd": target_hwnd,
                "title": title,
                "action": "maximized",
                "message": f"Successfully maximized window '{title}' (HWND: {target_hwnd}).",
            }
        except Exception as exc:
            logger.exception("Failed to maximize window %s: %s", target_hwnd, exc)
            return {
                "success": False,
                "hwnd": target_hwnd,
                "title": title,
                "error": f"Failed to maximize window: {exc}",
            }
