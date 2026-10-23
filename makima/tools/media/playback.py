"""
Makima v2 — Windows Media Transport Controls.
Architectural Pattern: Direct async WinRT integration via winrt.windows.media.control.
Rule 6: Clean, modular Makima v2 code. Zero copy-paste from v1.
Rule 7: Library-first using official Windows Runtime (WinRT) APIs.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import winrt.windows.media.control as wmc

from makima.tools.registry import tool

logger = logging.getLogger(__name__)


async def _get_media_session_manager() -> Optional[wmc.GlobalSystemMediaTransportControlsSessionManager]:
    """Helper to safely obtain the WinRT media session manager."""
    try:
        return await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
    except Exception as exc:
        logger.warning("Failed to obtain MediaTransportControlsSessionManager: %s", exc)
        return None


async def _get_active_session(
    manager: wmc.GlobalSystemMediaTransportControlsSessionManager,
) -> Optional[wmc.GlobalSystemMediaTransportControlsSession]:
    """Retrieves current or first available media session."""
    session = manager.get_current_session()
    if session is not None:
        return session

    sessions = manager.get_sessions()
    if sessions:
        return sessions[0]

    return None


@tool(
    name="control_media",
    description="Controls media playback (play, pause, play_pause, next, previous, stop) on Windows via WinRT.",
    tags=["media", "playback", "windows"],
)
async def control_media(action: str) -> Dict[str, Any]:
    """
    Control active Windows media session playback.

    Args:
        action: Transport action to perform ('play', 'pause', 'play_pause', 'next', 'previous', 'stop').
    """
    action_clean = action.strip().lower().replace("-", "_").replace(" ", "_").replace("/", "_")
    valid_actions = {"play", "pause", "play_pause", "toggle", "next", "skip", "previous", "prev", "stop"}

    if action_clean not in valid_actions:
        return {
            "success": False,
            "action": action,
            "error": f"Unsupported media action '{action}'. Supported: play, pause, play_pause, next, previous, stop.",
        }

    manager = await _get_media_session_manager()
    if manager is None:
        return {
            "success": False,
            "action": action_clean,
            "error": "Windows Media Transport Controls Session Manager is unavailable.",
        }

    session = await _get_active_session(manager)
    if session is None:
        return {
            "success": False,
            "action": action_clean,
            "message": "No active media session found.",
            "source_app": None,
        }

    source_app = session.source_app_user_model_id or "unknown"
    success = False

    try:
        if action_clean == "play":
            success = await session.try_play_async()
        elif action_clean == "pause":
            success = await session.try_pause_async()
        elif action_clean in ("play_pause", "toggle"):
            success = await session.try_toggle_play_pause_async()
        elif action_clean in ("next", "skip"):
            success = await session.try_skip_next_async()
        elif action_clean in ("previous", "prev"):
            success = await session.try_skip_previous_async()
        elif action_clean == "stop":
            success = await session.try_stop_async()
    except Exception as exc:
        logger.warning("Error dispatching media control '%s' to %s: %s", action_clean, source_app, exc)
        return {
            "success": False,
            "action": action_clean,
            "source_app": source_app,
            "error": str(exc),
        }

    return {
        "success": bool(success),
        "action": action_clean,
        "source_app": source_app,
        "message": (
            f"Successfully executed '{action_clean}' on {source_app}."
            if success
            else f"Media player {source_app} did not accept command '{action_clean}'."
        ),
    }


@tool(
    name="get_media_status",
    description="Retrieves current active media playback info including song title, artist, album, and status.",
    tags=["media", "status", "windows"],
)
async def get_media_status() -> Dict[str, Any]:
    """
    Get active media playback info and metadata from Windows.
    """
    manager = await _get_media_session_manager()
    if manager is None:
        return {
            "active": False,
            "message": "Windows Media Transport Controls Session Manager is unavailable.",
            "source_app": None,
            "title": None,
            "artist": None,
            "playback_status": "none",
        }

    session = await _get_active_session(manager)
    if session is None:
        return {
            "active": False,
            "message": "No active media session found.",
            "source_app": None,
            "title": None,
            "artist": None,
            "playback_status": "none",
        }

    source_app = session.source_app_user_model_id or "unknown"
    info = session.get_playback_info()
    playback_status = (
        info.playback_status.name.lower()
        if info and hasattr(info, "playback_status")
        else "unknown"
    )

    title = ""
    artist = ""
    album = ""

    try:
        props = await session.try_get_media_properties_async()
        if props is not None:
            title = props.title or ""
            artist = props.artist or ""
            album = props.album_title or ""
    except Exception as exc:
        logger.debug("Failed to retrieve media properties: %s", exc)

    return {
        "active": True,
        "source_app": source_app,
        "title": title,
        "artist": artist,
        "album": album,
        "playback_status": playback_status,
    }
