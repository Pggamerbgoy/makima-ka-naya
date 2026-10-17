"""
Makima v2 — Media & Audio Tools.
Provides native Windows media playback and master volume/mute controls.
"""

from makima.tools.media.play_song import play_song
from makima.tools.media.playback import control_media, get_media_status
from makima.tools.media.volume import get_volume, set_volume, toggle_mute

__all__ = [
    "control_media",
    "get_media_status",
    "get_volume",
    "play_song",
    "set_volume",
    "toggle_mute",
]
