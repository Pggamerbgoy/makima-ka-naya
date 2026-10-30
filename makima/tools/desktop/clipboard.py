"""
Makima v2 — Native OS Clipboard Management Tools.
Provides hardware-level reading, writing, and clearing of the system clipboard.
Uses pywin32 win32clipboard / Win32 ctypes with cross-platform fallback.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
from typing import Any, Dict

from makima.tools.registry import tool

logger = logging.getLogger(__name__)

CF_UNICODETEXT = 13


def _open_clipboard_win32():
    """Context manager or helper for Win32 clipboard access."""
    try:
        import win32clipboard
        import win32con

        return win32clipboard, win32con
    except ImportError:
        return None, None


@tool(
    name="get_clipboard_text",
    description="Read the current text content from the local operating system clipboard.",
    tags=["desktop", "clipboard", "os"],
    purpose="Retrieve text previously copied by the user or an application.",
    capabilities=["Read Unicode text from the system clipboard safely."],
    side_effect="Read-only; does not alter clipboard contents.",
)
def get_clipboard_text() -> Dict[str, Any]:
    """
    Read text from the system clipboard.

    Returns:
        Dictionary with success status, text content, and character count.
    """
    # Strategy 1: pywin32 win32clipboard
    wcb, wcon = _open_clipboard_win32()
    if wcb and wcon:
        try:
            wcb.OpenClipboard()
            try:
                if wcb.IsClipboardFormatAvailable(wcon.CF_UNICODETEXT):
                    data = wcb.GetClipboardData(wcon.CF_UNICODETEXT)
                    text = str(data) if data is not None else ""
                    return {
                        "success": True,
                        "text": text,
                        "length": len(text),
                        "empty": len(text) == 0,
                    }
                elif wcb.IsClipboardFormatAvailable(wcon.CF_TEXT):
                    data = wcb.GetClipboardData(wcon.CF_TEXT)
                    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data or "")
                    return {
                        "success": True,
                        "text": text,
                        "length": len(text),
                        "empty": len(text) == 0,
                    }
                else:
                    return {
                        "success": True,
                        "text": "",
                        "length": 0,
                        "empty": True,
                        "note": "Clipboard contains non-text data (e.g. image, file list).",
                    }
            finally:
                wcb.CloseClipboard()
        except Exception as exc:
            logger.debug("win32clipboard failed: %s, trying ctypes", exc)

    # Strategy 2: ctypes Win32
    if hasattr(ctypes, "windll"):
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            if user32.OpenClipboard(None):
                try:
                    handle = user32.GetClipboardData(CF_UNICODETEXT)
                    if handle:
                        kernel32.GlobalLock.restype = ctypes.c_wchar_p
                        ptr = kernel32.GlobalLock(handle)
                        text = str(ptr) if ptr else ""
                        kernel32.GlobalUnlock(handle)
                        return {
                            "success": True,
                            "text": text,
                            "length": len(text),
                            "empty": len(text) == 0,
                        }
                    else:
                        return {
                            "success": True,
                            "text": "",
                            "length": 0,
                            "empty": True,
                        }
                finally:
                    user32.CloseClipboard()
        except Exception as exc:
            logger.debug("ctypes clipboard reading failed: %s", exc)

    # Strategy 3: PowerShell (Windows) or platform utility
    if os.name == "nt":
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                txt = res.stdout.rstrip("\r\n")
                return {
                    "success": True,
                    "text": txt,
                    "length": len(txt),
                    "empty": len(txt) == 0,
                }
        except Exception as exc:
            logger.debug("PowerShell Get-Clipboard failed: %s", exc)
    else:
        # Linux/Unix fallback
        for cmd in [["xclip", "-o", "-selection", "clipboard"], ["wl-paste"], ["pbpaste"]]:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    return {
                        "success": True,
                        "text": res.stdout,
                        "length": len(res.stdout),
                        "empty": len(res.stdout) == 0,
                    }
            except Exception:
                continue

    return {
        "success": False,
        "error": "Unable to access system clipboard in current environment.",
    }


@tool(
    name="set_clipboard_text",
    description="Set or copy text into the local operating system clipboard.",
    tags=["desktop", "clipboard", "os"],
    purpose="Copy text programmatically to the OS clipboard for pasting into other apps.",
    capabilities=["Write Unicode text into the system clipboard."],
    side_effect="Overwrites the current system clipboard text.",
)
def set_clipboard_text(text: str) -> Dict[str, Any]:
    """
    Write text to the system clipboard.

    Args:
        text: The string to place onto the clipboard.

    Returns:
        Dictionary reporting success and character count.
    """
    if not isinstance(text, str):
        text = str(text)

    # Strategy 1: pywin32 win32clipboard
    wcb, wcon = _open_clipboard_win32()
    if wcb and wcon:
        try:
            wcb.OpenClipboard()
            try:
                wcb.EmptyClipboard()
                wcb.SetClipboardData(wcon.CF_UNICODETEXT, text)
                return {
                    "success": True,
                    "chars_copied": len(text),
                    "message": f"Successfully copied {len(text)} character(s) to clipboard.",
                }
            finally:
                wcb.CloseClipboard()
        except Exception as exc:
            logger.debug("win32clipboard write failed: %s, trying ctypes", exc)

    # Strategy 2: ctypes Win32
    if hasattr(ctypes, "windll"):
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            GMEM_MOVEABLE = 0x0002
            buf = text.encode("utf-16le") + b"\x00\x00"
            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(buf))
            if h_mem:
                p_mem = kernel32.GlobalLock(h_mem)
                ctypes.memmove(p_mem, buf, len(buf))
                kernel32.GlobalUnlock(h_mem)
                if user32.OpenClipboard(None):
                    try:
                        user32.EmptyClipboard()
                        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                        return {
                            "success": True,
                            "chars_copied": len(text),
                            "message": f"Successfully copied {len(text)} character(s) to clipboard.",
                        }
                    finally:
                        user32.CloseClipboard()
        except Exception as exc:
            logger.debug("ctypes clipboard writing failed: %s", exc)

    # Strategy 3: PowerShell (Windows) or platform utility
    if os.name == "nt":
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Set-Clipboard", "-Value", "$input"],
                input=text,
                text=True,
                capture_output=True,
                timeout=3,
            )
            if res.returncode == 0:
                return {
                    "success": True,
                    "chars_copied": len(text),
                    "message": f"Successfully copied {len(text)} character(s) to clipboard.",
                }
        except Exception as exc:
            logger.debug("PowerShell Set-Clipboard failed: %s", exc)
    else:
        # Linux/Unix fallback
        for cmd in [["xclip", "-selection", "clipboard"], ["wl-copy"], ["pbcopy"]]:
            try:
                res = subprocess.run(cmd, input=text, text=True, capture_output=True, timeout=2)
                if res.returncode == 0:
                    return {
                        "success": True,
                        "chars_copied": len(text),
                        "message": f"Successfully copied {len(text)} character(s) to clipboard.",
                    }
            except Exception:
                continue

    return {
        "success": False,
        "error": "Unable to write to system clipboard in current environment.",
    }


@tool(
    name="clear_clipboard",
    description="Clear all content currently stored on the local system clipboard.",
    tags=["desktop", "clipboard", "os"],
    purpose="Wipe sensitive data or reset the system clipboard.",
    side_effect="Empties the system clipboard.",
)
def clear_clipboard() -> Dict[str, Any]:
    """
    Clear the system clipboard.

    Returns:
        Dictionary indicating clear operation status.
    """
    return set_clipboard_text("")
