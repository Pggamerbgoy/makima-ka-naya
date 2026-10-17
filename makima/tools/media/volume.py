"""
Makima v2 — Windows Master Audio Volume & Mute Controls.
Architectural Pattern: Direct pycaw integration via AudioUtilities.GetSpeakers().
Rule 6: Clean, modular Makima v2 code. Zero copy-paste from v1.
Rule 7: Library-first using pycaw and Windows Core Audio Endpoint Volume APIs.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict

import comtypes
from pycaw.pycaw import AudioUtilities

from makima.tools.registry import tool

logger = logging.getLogger(__name__)


@contextmanager
def _com_initialized():
    """Context manager to ensure COM is initialized in current thread."""
    initialized = False
    try:
        comtypes.CoInitialize()
        initialized = True
    except Exception as exc:
        logger.debug("CoInitialize note: %s", exc)

    try:
        yield
    finally:
        if initialized:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass


@tool(
    name="get_volume",
    description="Gets the Windows master audio volume percentage (0.0 to 100.0) and mute status.",
    tags=["media", "volume", "audio", "windows"],
)
def get_volume() -> Dict[str, Any]:
    """
    Get current Windows master volume percentage and mute status.
    """
    with _com_initialized():
        speakers = AudioUtilities.GetSpeakers()
        if speakers is None:
            return {
                "success": False,
                "error": "Default audio speakers endpoint not found.",
                "volume_percent": 0.0,
                "is_muted": False,
            }

        vol_percent = float(speakers.volume_percent)
        is_muted = bool(speakers.EndpointVolume.GetMute())
        device_name = getattr(speakers, "FriendlyName", "Speakers")

        return {
            "success": True,
            "volume_percent": round(vol_percent, 1),
            "is_muted": is_muted,
            "device": device_name,
        }


@tool(
    name="set_volume",
    description="Sets the Windows master audio volume percentage (clamps between 0.0 and 100.0).",
    tags=["media", "volume", "audio", "windows"],
)
def set_volume(percent: float) -> Dict[str, Any]:
    """
    Set Windows master audio volume percentage.

    Args:
        percent: Target volume level from 0.0 to 100.0.
    """
    target = max(0.0, min(100.0, float(percent)))

    with _com_initialized():
        speakers = AudioUtilities.GetSpeakers()
        if speakers is None:
            return {
                "success": False,
                "error": "Default audio speakers endpoint not found.",
            }

        previous = float(speakers.volume_percent)
        speakers.volume_percent = target
        current = float(speakers.volume_percent)
        is_muted = bool(speakers.EndpointVolume.GetMute())

        return {
            "success": True,
            "volume_percent": round(current, 1),
            "previous_volume": round(previous, 1),
            "is_muted": is_muted,
        }


@tool(
    name="toggle_mute",
    description="Toggles the Windows master audio mute status.",
    tags=["media", "volume", "audio", "windows"],
)
def toggle_mute() -> Dict[str, Any]:
    """
    Toggle Windows master audio mute state.
    """
    with _com_initialized():
        speakers = AudioUtilities.GetSpeakers()
        if speakers is None:
            return {
                "success": False,
                "error": "Default audio speakers endpoint not found.",
            }

        endpoint = speakers.EndpointVolume
        currently_muted = bool(endpoint.GetMute())
        new_mute_state = not currently_muted

        endpoint.SetMute(int(new_mute_state), None)
        vol_percent = float(speakers.volume_percent)

        return {
            "success": True,
            "is_muted": new_mute_state,
            "volume_percent": round(vol_percent, 1),
        }
