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
    description="Reads the current Windows master audio volume percentage (0.0 to 100.0) and mute status without changing anything.",
    tags=["media", "volume", "audio", "windows"],
    purpose="Read the current system-wide output volume and mute state.",
    capabilities=["Report current master volume percentage, mute status, and output device."],
    use_when=["The user asks what the current system volume or mute state is."],
    avoid_when=["The user asks to change volume or mute state; use set_volume or toggle_mute respectively."],
    examples=["Check the current master volume."],
    side_effect="Read-only; does not change audio settings.",
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
    description="Sets the Windows master output volume to an explicit percentage from 0.0 to 100.0.",
    tags=["media", "volume", "audio", "windows"],
    purpose="Set the system-wide master output volume to a requested level.",
    capabilities=["Set an exact master volume percentage; values are clamped to 0–100."],
    use_when=["The user explicitly requests a volume level or asks to raise/lower volume by a clear amount."],
    avoid_when=["The user asks to pause/stop/resume a track; use control_media.","The user asks only whether audio is muted or what the current volume is; use get_volume."],
    examples=["Set system volume to 40 percent.","Lower volume to 25 percent."],
    side_effect="Changes system-wide output volume.",
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
    description="Toggles the Windows system-wide master output mute state; it does not change the volume percentage.",
    tags=["media", "volume", "audio", "windows"],
    purpose="Toggle the system-wide audio mute state.",
    capabilities=["Mute currently unmuted audio or unmute currently muted audio."],
    use_when=["The user explicitly asks to mute or unmute system audio without specifying a new volume percentage."],
    avoid_when=["The user specifies an exact volume percentage; use set_volume.","The user asks to stop/pause a song or video; use control_media."],
    examples=["Mute system audio.","Unmute the speakers."],
    side_effect="Changes system-wide mute state.",
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
