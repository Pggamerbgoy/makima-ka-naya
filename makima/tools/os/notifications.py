"""
Makima v2 — Native Windows Desktop Toast Alerts via win11toast.
Architectural Pattern: Clean, modular, library-first Windows Action Center notifications.
Features:
- Native WinRT Action Center notifications using win11toast.
- Zero PowerShell subprocess overhead.
- Interactive action buttons and speech dialogue synthesis support.
- Non-blocking dispatch by default to keep agent loops responsive.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

import win11toast

from makima.tools.registry import tool

logger = logging.getLogger(__name__)

# Patch upstream win11toast.speak to support both callable and property content_type (Python 3.14 / WinRT compatibility)
_upstream_speak = win11toast.speak


async def _patched_speak(text: str) -> None:
    try:
        from winrt.windows.media.core import MediaSource
        from winrt.windows.media.playback import MediaPlayer
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer

        stream = await SpeechSynthesizer().synthesize_text_to_stream_async(text)
        player = MediaPlayer()
        ct = stream.content_type() if callable(getattr(stream, "content_type", None)) else stream.content_type
        player.source = MediaSource.create_from_stream(stream, ct)
        player.play()
        # Keep speech alive briefly during playback
        await win11toast.asyncio.sleep(3)
    except Exception as exc:
        logger.debug("WinRT SpeechSynthesizer dialogue playback skipped: %s", exc)


win11toast.speak = _patched_speak



@tool(
    name="show_desktop_notification",
    description=(
        "Use when you want to alert the user with a Windows toast notification — "
        "task completion, reminders, errors, or status updates. "
        "Shows in the Action Center without interrupting the active window. "
        "For spoken alerts, pass dialogue text."
    ),
    tags=["os", "desktop", "notifications"],
)
def show_desktop_notification(
    title: str,
    message: str,
    buttons: Optional[List[str]] = None,
    dialogue: Optional[str] = None,
    wait: bool = False,
) -> Dict[str, Any]:
    """
    Display a native Windows toast notification alert.

    Args:
        title: Notification header text displayed in Windows Action Center.
        message: Main notification body text.
        buttons: Optional list of button label strings for interactive notifications (e.g. ['Open', 'Dismiss']).
        dialogue: Optional text to be spoken aloud via Windows SpeechSynthesizer.
        wait: If True, blocks until the toast is dismissed or activated. If False (default), dispatches asynchronously.

    Returns:
        Dictionary reporting notification delivery status, title, message, and configuration.
    """
    if not title or not title.strip():
        return {
            "success": False,
            "error": "The 'title' parameter cannot be empty.",
        }

    if not message or not message.strip():
        return {
            "success": False,
            "error": "The 'message' parameter cannot be empty.",
        }

    clean_title = title.strip()
    clean_message = message.strip()

    # Normalize buttons list
    toast_buttons = [b.strip() for b in buttons if b and b.strip()] if buttons else []

    try:
        kwargs: Dict[str, Any] = {}
        if toast_buttons:
            kwargs["buttons"] = toast_buttons
        if dialogue and dialogue.strip():
            kwargs["dialogue"] = dialogue.strip()

        if wait:
            # Synchronous: blocks until user interacts or notification times out
            result = win11toast.toast(clean_title, clean_message, **kwargs)
            return {
                "success": True,
                "title": clean_title,
                "message": clean_message,
                "buttons": toast_buttons or None,
                "dialogue": dialogue,
                "result": result,
                "dispatched": True,
                "status": "Notification displayed and interacted/dismissed.",
            }

        # Asynchronous (default): Fire-and-forget in background thread to avoid blocking agent
        dispatch_exception: List[Exception] = []

        def _dispatch_toast() -> None:
            try:
                win11toast.toast(clean_title, clean_message, **kwargs)
            except Exception as exc:
                dispatch_exception.append(exc)
                logger.warning("Error during toast notification dispatch: %s", exc)

        toast_thread = threading.Thread(
            target=_dispatch_toast,
            name=f"Toast-{clean_title[:15]}",
            daemon=True,
        )
        toast_thread.start()
        # Brief join to ensure the WinRT COM notification initialized without immediate crash
        toast_thread.join(timeout=0.15)

        if dispatch_exception:
            raise dispatch_exception[0]

        return {
            "success": True,
            "title": clean_title,
            "message": clean_message,
            "buttons": toast_buttons or None,
            "dialogue": dialogue,
            "dispatched": True,
            "status": "Notification successfully dispatched to Windows Action Center.",
        }

    except Exception as exc:
        logger.exception("Failed to dispatch desktop notification: %s", exc)
        return {
            "success": False,
            "title": clean_title,
            "message": clean_message,
            "error": f"Failed to dispatch desktop notification: {exc}",
        }
