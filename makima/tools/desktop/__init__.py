"""
Makima v2 — Desktop Tools Package.
Universal Zero-Vision Microsoft UI Automation (UIA) tools.
"""

from makima.tools.desktop.clipboard import (
    clear_clipboard,
    get_clipboard_text,
    set_clipboard_text,
)
from makima.tools.desktop.computer_use import computer_use
from makima.tools.desktop.input import (
    get_cursor_position,
    keyboard_hotkey,
    keyboard_type,
    mouse_click,
    mouse_drag,
    mouse_move,
    mouse_scroll,
)
from makima.tools.desktop.screen import (
    capture_screen,
    capture_window,
)
from makima.tools.desktop.som import (
    annotate_window_som,
    get_last_som_marks,
)
from makima.tools.desktop.uia import (
    click_ui_element,
    inspect_app_ui,
    read_ui_text,
    send_keys_to_app,
    set_ui_text,
)

__all__ = [
    "computer_use",
    "inspect_app_ui",
    "click_ui_element",
    "set_ui_text",
    "read_ui_text",
    "send_keys_to_app",
    "capture_window",
    "capture_screen",
    "annotate_window_som",
    "get_last_som_marks",
    "mouse_move",
    "mouse_click",
    "mouse_drag",
    "mouse_scroll",
    "keyboard_type",
    "keyboard_hotkey",
    "get_cursor_position",
    # Clipboard tools
    "get_clipboard_text",
    "set_clipboard_text",
    "clear_clipboard",
]
