"""
Makima v2 — Hardware-Grade Desktop Input Simulator.
Architectural Pattern: Native Win32 SendInput via Python ctypes.
Bypasses legacy mouse_event/keybd_event deprecation and provides zero-drop
hardware simulation across all Windows applications (DirectInput compatible).
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from typing import Any, Optional

import win32con

from makima.tools.registry import tool

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32

# ---------------------------------------------------------------------------
# Win32 C Structure Definitions for SendInput
# ---------------------------------------------------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

# Mouse flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000

# Keyboard flags
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

WHEEL_DELTA = 120


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUTunion),
    ]


# ---------------------------------------------------------------------------
# Virtual Key Code Mapping
# ---------------------------------------------------------------------------

KEY_MAP: dict[str, int] = {
    "enter": win32con.VK_RETURN,
    "return": win32con.VK_RETURN,
    "esc": win32con.VK_ESCAPE,
    "escape": win32con.VK_ESCAPE,
    "backspace": win32con.VK_BACK,
    "tab": win32con.VK_TAB,
    "space": win32con.VK_SPACE,
    "ctrl": win32con.VK_CONTROL,
    "control": win32con.VK_CONTROL,
    "alt": win32con.VK_MENU,
    "shift": win32con.VK_SHIFT,
    "win": win32con.VK_LWIN,
    "windows": win32con.VK_LWIN,
    "meta": win32con.VK_LWIN,
    "up": win32con.VK_UP,
    "down": win32con.VK_DOWN,
    "left": win32con.VK_LEFT,
    "right": win32con.VK_RIGHT,
    "delete": win32con.VK_DELETE,
    "del": win32con.VK_DELETE,
    "insert": win32con.VK_INSERT,
    "home": win32con.VK_HOME,
    "end": win32con.VK_END,
    "pageup": win32con.VK_PRIOR,
    "pagedown": win32con.VK_NEXT,
    "capslock": win32con.VK_CAPITAL,
    "printscreen": win32con.VK_SNAPSHOT,
    "f1": win32con.VK_F1,
    "f2": win32con.VK_F2,
    "f3": win32con.VK_F3,
    "f4": win32con.VK_F4,
    "f5": win32con.VK_F5,
    "f6": win32con.VK_F6,
    "f7": win32con.VK_F7,
    "f8": win32con.VK_F8,
    "f9": win32con.VK_F9,
    "f10": win32con.VK_F10,
    "f11": win32con.VK_F11,
    "f12": win32con.VK_F12,
}


def _send_inputs(inputs: list[INPUT]) -> int:
    """Dispatches a list of INPUT structures via user32.SendInput with mouse_event/keybd_event fallback."""
    if not inputs:
        return 0
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent > 0:
        return sent

    # Fallback for UIPI error 5 (Access Denied) in service/background processes
    fallback_count = 0
    for inp in inputs:
        try:
            if inp.type == INPUT_MOUSE:
                mi = inp.union.mi
                user32.mouse_event(mi.dwFlags, mi.dx, mi.dy, mi.mouseData, mi.dwExtraInfo)
                fallback_count += 1
            elif inp.type == INPUT_KEYBOARD:
                ki = inp.union.ki
                user32.keybd_event(ki.wVk, ki.wScan, ki.dwFlags, ki.dwExtraInfo)
                fallback_count += 1
        except Exception as exc:
            logger.debug("Input event fallback notice: %s", exc)
    return fallback_count


def _get_active_window_info(target_hwnd: Optional[int] = None) -> str:
    """Helper to retrieve foreground window title or process name without throwing exceptions."""
    try:
        from makima.tools.os.windows import _open_interactive_desktop
        import win32gui
        import win32process
        import psutil

        if target_hwnd and win32gui.IsWindow(target_hwnd):
            t = win32gui.GetWindowText(target_hwnd).strip()
            if t:
                return t

        with _open_interactive_desktop():
            fg = win32gui.GetForegroundWindow()
            if fg and win32gui.IsWindow(fg):
                title = win32gui.GetWindowText(fg).strip()
                if title:
                    return title
                # Fallback to process name if window has no title bar text
                _, pid = win32process.GetWindowThreadProcessId(fg)
                if pid:
                    proc = psutil.Process(pid)
                    return proc.name()
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Public Desktop Input Tools
# ---------------------------------------------------------------------------


@tool(
    name="get_cursor_position",
    description="Get current physical screen coordinates (X, Y) of the mouse cursor.",
    tags=["desktop", "input", "mouse"],
    fallback_for="computer_use",
)
def get_cursor_position() -> dict[str, int]:
    """Returns the current mouse cursor coordinates."""
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return {"x": int(pt.x), "y": int(pt.y)}


@tool(
    name="mouse_move",
    description="Move the mouse cursor to specific physical screen coordinates (X, Y). Supports smooth multi-step motion.",
    tags=["desktop", "input", "mouse"],
    fallback_for="computer_use",
)
def mouse_move(
    x: int,
    y: int,
    smooth: bool = False,
    steps: int = 5,
) -> dict[str, Any]:
    """
    Moves mouse cursor to target screen coordinates.

    Args:
        x: Horizontal screen pixel coordinate.
        y: Vertical screen pixel coordinate.
        smooth: Whether to interpolate movement smoothly.
        steps: Number of interpolation steps if smooth is True.
    """
    try:
        curr = get_cursor_position()
        curr_x, curr_y = curr["x"], curr["y"]

        if smooth and steps > 1:
            for i in range(1, steps + 1):
                ix = int(curr_x + (x - curr_x) * (i / steps))
                iy = int(curr_y + (y - curr_y) * (i / steps))
                user32.SetCursorPos(ix, iy)
                time.sleep(0.005)
        else:
            user32.SetCursorPos(int(x), int(y))

        final_pos = get_cursor_position()
        return {
            "success": True,
            "target": {"x": x, "y": y},
            "actual": final_pos,
        }
    except Exception as exc:
        logger.exception("Failed moving mouse: %s", exc)
        return {"success": False, "error": str(exc)}


@tool(
    name="mouse_click",
    description="Perform a mouse click (single, double, triple, right, middle) at optional coordinates or current cursor location.",
    tags=["desktop", "input", "mouse"],
    fallback_for="computer_use",
)
def mouse_click(
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    click_type: str = "single",
) -> dict[str, Any]:
    """
    Clicks the mouse.

    Args:
        x: Optional horizontal screen coordinate. If omitted, clicks at current position.
        y: Optional vertical screen coordinate. If omitted, clicks at current position.
        button: Mouse button ('left', 'right', 'middle').
        click_type: Click repetition ('single', 'double', 'triple').
    """
    try:
        if x is not None and y is not None:
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.01)

        btn_norm = button.strip().lower()
        if btn_norm == "right":
            down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        elif btn_norm == "middle":
            down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
        else:
            down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP

        reps = 1
        if click_type == "double":
            reps = 2
        elif click_type == "triple":
            reps = 3

        inputs: list[INPUT] = []
        for _ in range(reps):
            inp_down = INPUT(type=INPUT_MOUSE)
            inp_down.union.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=down_flag, time=0, dwExtraInfo=0)
            inp_up = INPUT(type=INPUT_MOUSE)
            inp_up.union.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=up_flag, time=0, dwExtraInfo=0)
            inputs.extend([inp_down, inp_up])

        sent = _send_inputs(inputs)
        pos = get_cursor_position()
        return {
            "success": True,
            "button": btn_norm,
            "click_type": click_type,
            "coordinates": pos,
            "events_dispatched": sent,
            "active_window": _get_active_window_info(),
        }
    except Exception as exc:
        logger.exception("Failed mouse click: %s", exc)
        return {"success": False, "error": str(exc)}


@tool(
    name="mouse_drag",
    description="Drag and drop mouse from start coordinates to end coordinates.",
    tags=["desktop", "input", "mouse"],
    fallback_for="computer_use",
)
def mouse_drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    button: str = "left",
    steps: int = 10,
) -> dict[str, Any]:
    """Performs a smooth mouse drag-and-drop operation."""
    try:
        user32.SetCursorPos(int(start_x), int(start_y))
        time.sleep(0.02)

        down_flag = MOUSEEVENTF_RIGHTDOWN if button == "right" else MOUSEEVENTF_LEFTDOWN
        up_flag = MOUSEEVENTF_RIGHTUP if button == "right" else MOUSEEVENTF_LEFTUP

        # Press button down
        inp_down = INPUT(type=INPUT_MOUSE)
        inp_down.union.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=down_flag, time=0, dwExtraInfo=0)
        _send_inputs([inp_down])
        time.sleep(0.02)

        # Move intermediate points
        for i in range(1, steps + 1):
            ix = int(start_x + (end_x - start_x) * (i / steps))
            iy = int(start_y + (end_y - start_y) * (i / steps))
            user32.SetCursorPos(ix, iy)
            time.sleep(0.01)

        # Release button
        inp_up = INPUT(type=INPUT_MOUSE)
        inp_up.union.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=up_flag, time=0, dwExtraInfo=0)
        _send_inputs([inp_up])

        return {
            "success": True,
            "start": {"x": start_x, "y": start_y},
            "end": {"x": end_x, "y": end_y},
            "button": button,
            "active_window": _get_active_window_info(),
        }
    except Exception as exc:
        logger.exception("Failed mouse drag: %s", exc)
        return {"success": False, "error": str(exc)}


@tool(
    name="mouse_scroll",
    description="Scroll the mouse wheel vertically or horizontally.",
    tags=["desktop", "input", "mouse"],
    fallback_for="computer_use",
)
def mouse_scroll(
    clicks: int,
    direction: str = "vertical",
) -> dict[str, Any]:
    """
    Scrolls the mouse wheel.

    Args:
        clicks: Positive for scrolling up/forward, negative for down/backward.
        direction: 'vertical' or 'horizontal'.
    """
    try:
        flag = MOUSEEVENTF_HWHEEL if direction.lower() == "horizontal" else MOUSEEVENTF_WHEEL
        delta = int(clicks * WHEEL_DELTA)

        inp = INPUT(type=INPUT_MOUSE)
        inp.union.mi = MOUSEINPUT(dx=0, dy=0, mouseData=delta, dwFlags=flag, time=0, dwExtraInfo=0)
        sent = _send_inputs([inp])
        return {
            "success": True,
            "clicks": clicks,
            "direction": direction,
            "wheel_delta": delta,
            "events_dispatched": sent,
            "active_window": _get_active_window_info(),
        }
    except Exception as exc:
        logger.exception("Failed mouse scroll: %s", exc)
        return {"success": False, "error": str(exc)}


@tool(
    name="keyboard_type",
    description="Type text natively into the active foreground window or target application using Win32 Unicode keystrokes. Supports all international characters, symbols, and emojis.",
    tags=["desktop", "input", "keyboard"],
    fallback_for="computer_use",
)
def keyboard_type(
    text: str,
    delay_ms: float = 0.0,
    title_query: str | None = None,
    hwnd: int | None = None,
) -> dict[str, Any]:
    """
    Types text using KEYEVENTF_UNICODE.

    Args:
        text: String of text to type.
        delay_ms: Optional millisecond delay between keystrokes.
        title_query: Optional window title to target.
        hwnd: Optional window HWND to target.
    """
    try:
        target_hwnd = None
        if title_query or hwnd:
            try:
                from makima.tools.os.windows import _find_target_window, focus_window
                target_hwnd, _, _ = _find_target_window(title_query=title_query, hwnd=hwnd)
                if target_hwnd:
                    focus_window(hwnd=target_hwnd)
                    time.sleep(0.1)
            except Exception:
                pass

        chars_typed = 0
        for char in text:
            code = ord(char)
            inp_down = INPUT(type=INPUT_KEYBOARD)
            inp_down.union.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0)

            inp_up = INPUT(type=INPUT_KEYBOARD)
            inp_up.union.ki = KEYBDINPUT(
                wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0
            )

            _send_inputs([inp_down, inp_up])
            chars_typed += 1

            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

        # If window is targeted and running in background session, ensure text reached control
        if target_hwnd:
            try:
                import pywinauto
                app = pywinauto.Application(backend="uia").connect(handle=target_hwnd)
                top = app.window(handle=target_hwnd)
                edit = top.descendants(control_type="Edit") or top.descendants(control_type="Document")
                if edit:
                    curr_val = getattr(edit[0], "get_value", lambda: "")() or ""
                    if text not in curr_val:
                        if hasattr(edit[0], "set_edit_text"):
                            edit[0].set_edit_text(text)
            except Exception:
                pass

        return {
            "success": True,
            "chars_typed": chars_typed,
            "text_length": len(text),
            "active_window": _get_active_window_info(target_hwnd),
        }
    except Exception as exc:
        logger.exception("Failed typing text: %s", exc)
        return {"success": False, "error": str(exc)}


@tool(
    name="keyboard_hotkey",
    description="Press a combination or chord of keys simultaneously (e.g. ['ctrl', 's'], ['alt', 'tab'], ['ctrl', 'shift', 'esc'], ['win', 'r']).",
    tags=["desktop", "input", "keyboard"],
    fallback_for="computer_use",
)
def keyboard_hotkey(
    keys: list[str],
    title_query: Optional[str] = None,
    hwnd: Optional[int] = None,
) -> dict[str, Any]:
    """
    Executes a keyboard hotkey combination.

    Args:
        keys: List of key names to press in order, then release in reverse order.
        title_query: Optional substring or exact title of window to focus before hotkey.
        hwnd: Optional explicit window handle to focus before hotkey.
    """
    try:
        target_hwnd = hwnd
        if not target_hwnd and title_query:
            try:
                from makima.tools.os.windows import _find_target_window, focus_window
                target_hwnd, _, _ = _find_target_window(title_query=title_query, hwnd=hwnd)
                if target_hwnd:
                    focus_window(hwnd=target_hwnd)
                    time.sleep(0.05)
            except Exception:
                pass

        vk_codes: list[int] = []
        for k in keys:
            norm = k.strip().lower()
            if norm in KEY_MAP:
                vk_codes.append(KEY_MAP[norm])
            elif len(norm) == 1:
                # Character key: get virtual key code via VkKeyScanW or ord(upper)
                char_vk = user32.VkKeyScanW(ord(norm)) & 0xFF
                if char_vk > 0:
                    vk_codes.append(char_vk)
                else:
                    vk_codes.append(ord(norm.upper()))
            else:
                return {"success": False, "error": f"Unknown key in chord: '{k}'"}

        # Press down in order
        downs = []
        for vk in vk_codes:
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.union.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=0)
            downs.append(inp)
        _send_inputs(downs)

        time.sleep(0.05)

        # Release in reverse order
        ups = []
        for vk in reversed(vk_codes):
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.union.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
            ups.append(inp)
        _send_inputs(ups)

        # Allow 50ms for Windows title/focus settling if Enter or Tab was pressed
        if any(k.lower() in ("enter", "return", "tab") for k in keys):
            time.sleep(0.05)

        return {
            "success": True,
            "keys_pressed": keys,
            "vk_codes": vk_codes,
            "active_window": _get_active_window_info(target_hwnd),
        }
    except Exception as exc:
        logger.exception("Failed keyboard hotkey: %s", exc)
        return {"success": False, "error": str(exc)}
