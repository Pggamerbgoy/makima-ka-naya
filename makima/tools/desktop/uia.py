"""
Makima v2 — Zero-Vision Universal Desktop UI Automation.
Architectural Pattern: Direct Microsoft UI Automation (UIA) via pywinauto & pywin32.
Zero-Vision Guarantee: 100% programmatic control tree inspection, native InvokePattern,
ValuePattern text setting, and zero screenshot or pixel dependency.
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

import pythoncom
import pywinauto
import win32con
import win32gui
import win32service

from makima.tools.os.windows import _find_target_window
from makima.tools.registry import tool

logger = logging.getLogger(__name__)


def _init_desktop_thread() -> None:
    """Attaches the worker thread to the interactive desktop station and initializes COM STA once for thread lifetime."""
    try:
        desk = win32service.OpenDesktop("default", 0, False, win32con.GENERIC_ALL)
        desk.SetThreadDesktop()
    except Exception as exc:
        logger.debug("Desktop thread attachment notice: %s", exc)
    try:
        pythoncom.CoInitialize()
    except Exception as exc:
        logger.debug("COM STA init notice: %s", exc)


# Dedicated thread pool executor for COM STA and Desktop attachment isolation
_desktop_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="MakimaUIAWorker",
    initializer=_init_desktop_thread,
)


def _run_in_desktop_thread(fn, *args, **kwargs) -> Any:
    """
    Executes a callable inside a dedicated worker thread with persistent COM STA.
    Prevents Win32 COM threading model errors (0x80010106 RPC_E_CHANGED_MODE)
    and preserves pywinauto UIA COM cache across consecutive calls.
    """
    future = _desktop_executor.submit(fn, *args, **kwargs)
    return future.result(timeout=25.0)


def _element_to_dict(elem: Any, depth: int = 0) -> dict[str, Any]:
    """Extracts compact semantic metadata from a UIA element."""
    try:
        info = elem.element_info
        name = elem.window_text() or ""
        ctl_type = getattr(info, "control_type", "Unknown") or "Unknown"
        auto_id = getattr(info, "automation_id", "") or ""
        cls_name = getattr(info, "class_name", "") or ""

        # Bounding box
        rect = {}
        try:
            r = elem.rectangle()
            rect = {"left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom, "width": r.width(), "height": r.height()}
        except Exception:
            pass

        # Enabled / visible status
        is_enabled = True
        is_visible = True
        try:
            is_enabled = bool(elem.is_enabled())
            is_visible = bool(elem.is_visible())
        except Exception:
            pass

        return {
            "name": name.strip(),
            "control_type": str(ctl_type),
            "automation_id": str(auto_id).strip(),
            "class_name": str(cls_name).strip(),
            "enabled": is_enabled,
            "visible": is_visible,
            "rect": rect,
            "depth": depth,
        }
    except Exception as exc:
        logger.debug("Failed extracting element info: %s", exc)
        return {"name": "", "control_type": "Unknown", "depth": depth}


def _find_matching_child(
    parent_wrapper: Any,
    name: str | None = None,
    control_type: str | None = None,
    automation_id: str | None = None,
    class_name: str | None = None,
) -> Any | None:
    """Finds first matching descendant element adhering to filters."""
    descendants = parent_wrapper.descendants()
    name_norm = name.strip().lower() if name else None
    ctype_norm = control_type.strip().lower() if control_type else None
    aid_norm = automation_id.strip().lower() if automation_id else None
    cls_norm = class_name.strip().lower() if class_name else None

    # Pass 1: exact matches
    for d in descendants:
        try:
            info = d.element_info
            d_name = (d.window_text() or "").strip().lower()
            d_ctype = (getattr(info, "control_type", "") or "").strip().lower()
            d_aid = (getattr(info, "automation_id", "") or "").strip().lower()
            d_cls = (getattr(info, "class_name", "") or "").strip().lower()

            if name_norm and d_name != name_norm:
                continue
            if ctype_norm and d_ctype != ctype_norm:
                continue
            if aid_norm and d_aid != aid_norm:
                continue
            if cls_norm and d_cls != cls_norm:
                continue
            return d
        except Exception:
            continue

    # Pass 2: substring matches for name
    if name_norm:
        for d in descendants:
            try:
                d_name = (d.window_text() or "").strip().lower()
                info = d.element_info
                d_ctype = (getattr(info, "control_type", "") or "").strip().lower()

                if name_norm in d_name:
                    if ctype_norm and d_ctype != ctype_norm:
                        continue
                    return d
            except Exception:
                continue

    return None


@tool(
    name="inspect_app_ui",
    description="Inspect any Windows application control hierarchy via Microsoft UI Automation (UIA) without screenshots. Returns buttons, text boxes, menus, and controls.",
    tags=["desktop", "uia", "automation", "zero-vision"],
)
def inspect_app_ui(
    title_query: str | None = None,
    hwnd: int | None = None,
    max_elements: int = 60,
    include_empty_names: bool = False,
) -> dict[str, Any]:
    """
    Inspects the control tree of a target application using Microsoft UI Automation.

    Args:
        title_query: Substring or full title of window to inspect.
        hwnd: Specific HWND handle of the window.
        max_elements: Maximum number of controls to return (prevents token bloat).
        include_empty_names: Whether to include controls that have no text/label.

    Returns:
        Structured dictionary with window title, handle, control count, and controls list.
    """
    def _inspect():
        target_hwnd, title, err = _find_target_window(title_query=title_query, hwnd=hwnd)
        if target_hwnd is None or err:
            return {"success": False, "error": err or "Target window not found"}

        try:
            # Connect via pywinauto UIA backend
            app = pywinauto.Application(backend="uia").connect(handle=target_hwnd)
            top = app.window(handle=target_hwnd)

            descendants = top.descendants()
            items: list[dict[str, Any]] = []

            for d in descendants:
                node = _element_to_dict(d)
                if not include_empty_names and not node["name"] and not node["automation_id"]:
                    continue
                items.append(node)
                if len(items) >= max_elements:
                    break

            return {
                "success": True,
                "hwnd": target_hwnd,
                "window_title": title,
                "total_controls_found": len(items),
                "controls": items,
            }
        except Exception as exc:
            # Fallback to win32 backend if UIA fails on legacy window
            try:
                app_win32 = pywinauto.Application(backend="win32").connect(handle=target_hwnd)
                top_win32 = app_win32.window(handle=target_hwnd)
                children = top_win32.children()
                items = [_element_to_dict(c) for c in children[:max_elements]]
                return {
                    "success": True,
                    "hwnd": target_hwnd,
                    "window_title": title,
                    "backend_used": "win32_fallback",
                    "total_controls_found": len(items),
                    "controls": items,
                }
            except Exception as exc2:
                logger.exception("Failed inspecting app UI for HWND %s: %s | %s", target_hwnd, exc, exc2)
                return {
                    "success": False,
                    "hwnd": target_hwnd,
                    "window_title": title,
                    "error": f"Failed inspecting UI: {exc}",
                }

    return _run_in_desktop_thread(_inspect)


@tool(
    name="click_ui_element",
    description="Click or invoke a specific UI control (Button, MenuItem, Tab, ListItem) by name, control_type, or automation_id without vision.",
    tags=["desktop", "uia", "automation", "zero-vision"],
)
def click_ui_element(
    title_query: str | None = None,
    hwnd: int | None = None,
    name: str | None = None,
    control_type: str | None = None,
    automation_id: str | None = None,
    class_name: str | None = None,
) -> dict[str, Any]:
    """
    Clicks a UI element inside an application using native UIA InvokePattern or mouse click fallback.

    Args:
        title_query: Substring or title of target window.
        hwnd: Specific HWND of target window.
        name: Visible text or name of element (e.g. 'Save', 'Close', 'Submit').
        control_type: UIA control type (e.g. 'Button', 'MenuItem', 'TabItem', 'CheckBox').
        automation_id: UIA automation identifier.
        class_name: Windows class name.

    Returns:
        Operation outcome with clicked control metadata.
    """
    def _click():
        target_hwnd, title, err = _find_target_window(title_query=title_query, hwnd=hwnd)
        if target_hwnd is None or err:
            return {"success": False, "error": err or "Target window not found"}

        try:
            app = pywinauto.Application(backend="uia").connect(handle=target_hwnd)
            top = app.window(handle=target_hwnd)

            target_child = _find_matching_child(
                top,
                name=name,
                control_type=control_type,
                automation_id=automation_id,
                class_name=class_name,
            )

            if target_child is None:
                return {
                    "success": False,
                    "hwnd": target_hwnd,
                    "window_title": title,
                    "error": f"Control not found matching name={name!r}, control_type={control_type!r}, automation_id={automation_id!r}",
                }

            # 1. Try native UIA Invoke Pattern
            invoked = False
            try:
                if hasattr(target_child, "invoke"):
                    target_child.invoke()
                    invoked = True
            except Exception:
                pass

            # 2. If invoke not available or failed, use programmatic click
            if not invoked:
                target_child.click_input()

            return {
                "success": True,
                "hwnd": target_hwnd,
                "window_title": title,
                "action": "clicked",
                "clicked_element": _element_to_dict(target_child),
            }
        except Exception as exc:
            logger.exception("Failed clicking UI element: %s", exc)
            return {
                "success": False,
                "hwnd": target_hwnd,
                "window_title": title,
                "error": f"Failed clicking element: {exc}",
            }

    return _run_in_desktop_thread(_click)


@tool(
    name="set_ui_text",
    description="Type or set text in a specific UI text field, input, or search box using native UIA ValuePattern or keyboard typing.",
    tags=["desktop", "uia", "automation", "zero-vision"],
)
def set_ui_text(
    text: str,
    title_query: str | None = None,
    hwnd: int | None = None,
    name: str | None = None,
    control_type: str | None = "Edit",
    automation_id: str | None = None,
    clear_first: bool = True,
) -> dict[str, Any]:
    """
    Sets text into an edit or input control.

    Args:
        text: Text string to enter.
        title_query: Substring or title of target window.
        hwnd: Specific HWND of target window.
        name: Name or placeholder of the edit field.
        control_type: Control type, defaults to 'Edit'.
        automation_id: UIA automation identifier.
        clear_first: Whether to clear existing text before typing.

    Returns:
        Operation outcome.
    """
    def _set_text():
        target_hwnd, title, err = _find_target_window(title_query=title_query, hwnd=hwnd)
        if target_hwnd is None or err:
            return {"success": False, "error": err or "Target window not found"}

        try:
            app = pywinauto.Application(backend="uia").connect(handle=target_hwnd)
            top = app.window(handle=target_hwnd)

            target_child = _find_matching_child(
                top,
                name=name,
                control_type=control_type,
                automation_id=automation_id,
            )

            # Fallback to 'Document' for Windows 11 Notepad and rich text editors
            if target_child is None and (control_type or "").lower() == "edit":
                target_child = _find_matching_child(
                    top,
                    name=name,
                    control_type="Document",
                    automation_id=automation_id,
                )

            if target_child is None:
                return {
                    "success": False,
                    "hwnd": target_hwnd,
                    "window_title": title,
                    "error": f"Edit control not found matching name={name!r}, control_type={control_type!r}",
                }

            # 1. Native UIA set_edit_text / set_text
            text_set = False
            try:
                if hasattr(target_child, "set_edit_text"):
                    target_child.set_edit_text(text)
                    text_set = True
                elif hasattr(target_child, "set_text"):
                    target_child.set_text(text)
                    text_set = True
            except Exception:
                pass

            # 2. Programmatic key typing fallback
            if not text_set:
                target_child.click_input()
                if clear_first:
                    target_child.type_keys("^a{BACKSPACE}", with_spaces=True)
                target_child.type_keys(text, with_spaces=True)

            return {
                "success": True,
                "hwnd": target_hwnd,
                "window_title": title,
                "action": "text_set",
                "text": text,
                "target_element": _element_to_dict(target_child),
            }
        except Exception as exc:
            logger.exception("Failed setting UI text: %s", exc)
            return {
                "success": False,
                "hwnd": target_hwnd,
                "window_title": title,
                "error": f"Failed setting text: {exc}",
            }

    return _run_in_desktop_thread(_set_text)


@tool(
    name="read_ui_text",
    description="Read visible text and values from a specific UI control or an entire application window.",
    tags=["desktop", "uia", "automation", "zero-vision"],
)
def read_ui_text(
    title_query: str | None = None,
    hwnd: int | None = None,
    name: str | None = None,
    control_type: str | None = None,
    automation_id: str | None = None,
) -> dict[str, Any]:
    """
    Reads text content from a target element or entire window.

    Args:
        title_query: Window title query.
        hwnd: Window HWND.
        name: Specific element name.
        control_type: Specific element type.
        automation_id: Specific automation ID.

    Returns:
        Extracted text lines and control metadata.
    """
    def _read():
        target_hwnd, title, err = _find_target_window(title_query=title_query, hwnd=hwnd)
        if target_hwnd is None or err:
            return {"success": False, "error": err or "Target window not found"}

        try:
            app = pywinauto.Application(backend="uia").connect(handle=target_hwnd)
            top = app.window(handle=target_hwnd)

            if name or control_type or automation_id:
                child = _find_matching_child(top, name=name, control_type=control_type, automation_id=automation_id)
                if child:
                    child_text = ""
                    if hasattr(child, "get_value"):
                        try:
                            child_text = child.get_value() or ""
                        except Exception:
                            pass
                    if not child_text and hasattr(child, "legacy_properties"):
                        try:
                            child_text = child.legacy_properties().get("Value", "") or ""
                        except Exception:
                            pass
                    if not child_text:
                        child_text = child.window_text() or ""

                    return {
                        "success": True,
                        "hwnd": target_hwnd,
                        "window_title": title,
                        "text": child_text,
                        "element": _element_to_dict(child),
                    }
                return {"success": False, "error": "Specified child element not found"}

            # If no child filter, read all text content across all descendant controls
            desc = top.descendants()
            text_lines = []
            for d in desc:
                txt = (d.window_text() or "").strip()
                if txt and txt not in text_lines:
                    text_lines.append(txt)

            return {
                "success": True,
                "hwnd": target_hwnd,
                "window_title": title,
                "total_text_blocks": len(text_lines),
                "text_content": "\n".join(text_lines),
            }
        except Exception as exc:
            return {"success": False, "hwnd": target_hwnd, "error": f"Failed reading UI text: {exc}"}

    return _run_in_desktop_thread(_read)


@tool(
    name="send_keys_to_app",
    description="Send keyboard keystrokes, shortcuts, and navigation keys to an application window (e.g. '{ENTER}', '^s', '^f', '%{F4}').",
    tags=["desktop", "uia", "automation", "zero-vision"],
)
def send_keys_to_app(
    keys: str,
    title_query: str | None = None,
    hwnd: int | None = None,
) -> dict[str, Any]:
    """
    Brings target window to foreground and sends keyboard keys using pywinauto keystroke syntax.

    Keystroke syntax:
    - Normal text: 'hello'
    - Modifiers: '^' = Ctrl, '%' = Alt, '+' = Shift
    - Special keys: '{ENTER}', '{TAB}', '{ESC}', '{BACKSPACE}', '{UP}', '{DOWN}', '{LEFT}', '{RIGHT}'
    - Combinations: '^s' (Ctrl+S), '^f' (Ctrl+F), '%{F4}' (Alt+F4)

    Args:
        keys: Pywinauto keystroke string.
        title_query: Title of window to target.
        hwnd: Specific HWND.

    Returns:
        Operation outcome.
    """
    def _send():
        target_hwnd, title, err = _find_target_window(title_query=title_query, hwnd=hwnd)
        if target_hwnd is None or err:
            return {"success": False, "error": err or "Target window not found"}

        try:
            # Bring window to foreground
            if win32gui.IsIconic(target_hwnd):
                win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
            win32gui.BringWindowToTop(target_hwnd)
            try:
                win32gui.SetForegroundWindow(target_hwnd)
            except Exception as fg_exc:
                logger.debug("SetForegroundWindow soft-failed (lock held): %s", fg_exc)

            # Send keys: try global send_keys, fallback to window-level type_keys
            try:
                pywinauto.keyboard.send_keys(keys, with_spaces=True)
            except Exception as sk_exc:
                logger.debug("Global send_keys fallback to window type_keys: %s", sk_exc)
                app = pywinauto.Application(backend="uia").connect(handle=target_hwnd)
                app.window(handle=target_hwnd).type_keys(keys, with_spaces=True)

            return {
                "success": True,
                "hwnd": target_hwnd,
                "window_title": title,
                "action": "keys_sent",
                "keys": keys,
            }
        except Exception as exc:
            logger.exception("Failed sending keys to app: %s", exc)
            return {
                "success": False,
                "hwnd": target_hwnd,
                "window_title": title,
                "error": f"Failed sending keys: {exc}",
            }

    return _run_in_desktop_thread(_send)
