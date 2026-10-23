"""
Makima v2 — Media & Song Playback Tool.
Architectural Pattern: Hermes-style tool with direct YouTube/Spotify query resolution.
Zero-Hardcoding Guarantee: Fully dynamic platform resolution and cross-platform fallback.
Library-first: Direct use of youtube_search and stdlib webbrowser/os.
"""

from __future__ import annotations

import logging
import os
import re
import urllib.parse
import webbrowser
from typing import Any

from makima.tools.registry import tool

logger = logging.getLogger(__name__)


def _open_media_visible(url_or_path: str, browser: str | None = None) -> tuple[bool, str]:
    """
    Guarantees visible window launch on the interactive desktop (SW_SHOWNORMAL = 1).
    Avoids inheriting hidden window flags from background server daemons.
    """
    if not url_or_path:
        return False, "none"

    # Strategy 1: Explicit target browser (e.g. 'brave', 'chrome', 'edge', 'firefox')
    if browser:
        b_clean = browser.strip().lower()
        if os.name == "nt":
            try:
                import ctypes

                # SW_SHOWNORMAL = 1
                res = ctypes.windll.shell32.ShellExecuteW(None, "open", b_clean, url_or_path, None, 1)
                if res > 32:
                    return True, f"shellexecute_{b_clean}"
            except Exception as exc:  # noqa: BLE001
                logger.debug("ShellExecuteW failed for browser '%s': %s", b_clean, exc)

        try:
            b_inst = webbrowser.get(b_clean)
            if b_inst.open(url_or_path):
                return True, f"webbrowser_{b_clean}"
        except Exception as exc:  # noqa: BLE001
            logger.debug("webbrowser.get failed for browser '%s': %s", b_clean, exc)

    # Strategy 2: Native Windows Shell (os.startfile) which delegates to explorer.exe (always visible)
    if hasattr(os, "startfile"):
        try:
            os.startfile(url_or_path)
            return True, "os_startfile"
        except Exception as exc:  # noqa: BLE001
            logger.debug("os.startfile failed for '%s': %s", url_or_path, exc)

    # Strategy 3: Standard library webbrowser
    try:
        opened = webbrowser.open(url_or_path)
        return opened, "webbrowser"
    except Exception as exc:  # noqa: BLE001
        logger.warning("webbrowser.open failed for '%s': %s", url_or_path, exc)
        return False, "failed"


def _play_youtube(query: str, auto_open: bool, browser: str | None = None) -> dict[str, Any]:
    """Resolves YouTube video via YoutubeSearch and optionally opens playback."""
    video_id: str | None = None
    title: str = query
    channel: str | None = None
    duration: str | None = None
    url: str = ""

    # Strategy 1: YoutubeSearch library
    try:
        from youtube_search import YoutubeSearch
        results = YoutubeSearch(query, max_results=1).to_dict()
        if results and len(results) > 0:
            first = results[0]
            video_id = first.get("id")
            title = first.get("title", query)
            channel = first.get("channel")
            duration = first.get("duration")
            if video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
    except Exception as exc:  # noqa: BLE001
        logger.debug("YoutubeSearch library call failed for '%s': %s", query, exc)

    # Strategy 2: Direct HTTP fetch with regex fallback if YoutubeSearch encountered parsing issue
    if not video_id:
        try:
            import asyncio
            import concurrent.futures
            import httpx

            search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }

            async def _fetch_youtube_html() -> tuple[int, str]:
                async with httpx.AsyncClient(timeout=5.0, headers=headers, follow_redirects=True) as client:
                    resp = await client.get(search_url)
                    return resp.status_code, resp.text

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    status_code, resp_text = executor.submit(asyncio.run, _fetch_youtube_html()).result(timeout=6.0)
            else:
                status_code, resp_text = asyncio.run(_fetch_youtube_html())

            if status_code == 200:
                match = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp_text)
                if not match:
                    match = re.search(r'/watch\?v=([a-zA-Z0-9_-]{11})', resp_text)
                if match:
                    video_id = match.group(1)
                    url = f"https://www.youtube.com/watch?v={video_id}"
                    title_match = re.search(r'"title":\{"runs":\[\{"text":"([^"]+)"', resp_text)
                    if title_match:
                        title = title_match.group(1)
        except Exception as exc:  # noqa: BLE001
            logger.debug("YouTube fallback regex search failed for '%s': %s", query, exc)

    if not url:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"

    opened = False
    launch_method: str | None = None
    if auto_open and url:
        opened, launch_method = _open_media_visible(url, browser=browser)

    return {
        "status": "success",
        "platform": "youtube",
        "query": query,
        "title": title,
        "videoId": video_id,
        "video_id": video_id,
        "url": url,
        "channel": channel,
        "duration": duration,
        "auto_open": auto_open,
        "opened": opened if auto_open else False,
        "launch_method": launch_method,
    }


def _play_spotify(query: str, auto_open: bool, browser: str | None = None) -> dict[str, Any]:
    """Resolves Spotify URI and optionally opens playback via native app or browser."""
    encoded = urllib.parse.quote(query)
    spotify_uri = f"spotify:search:{query}"
    web_url = f"https://open.spotify.com/search/{encoded}"

    opened = False
    launch_method: str | None = None

    if auto_open:
        # Native Windows startfile for desktop Spotify application protocol
        if hasattr(os, "startfile"):
            try:
                os.startfile(spotify_uri)
                opened = True
                launch_method = "startfile_uri"
            except Exception as exc:  # noqa: BLE001
                logger.debug("os.startfile failed for Spotify URI '%s': %s", spotify_uri, exc)

        # Fallback to browser if startfile failed or platform is non-Windows
        if not opened:
            opened, launch_method = _open_media_visible(web_url, browser=browser)

    return {
        "status": "success",
        "platform": "spotify",
        "query": query,
        "title": f"Spotify: {query}",
        "videoId": None,
        "video_id": None,
        "uri": spotify_uri,
        "url": web_url,
        "auto_open": auto_open,
        "opened": opened if auto_open else False,
        "launch_method": launch_method,
    }


def _play_soundcloud(query: str, auto_open: bool, browser: str | None = None) -> dict[str, Any]:
    """Resolves and opens SoundCloud search for the query."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://soundcloud.com/search?q={encoded}"
    opened, launch_method = _open_media_visible(url, browser=browser) if auto_open else (False, None)
    return {
        "status": "success",
        "platform": "soundcloud",
        "query": query,
        "title": f"SoundCloud: {query}",
        "url": url,
        "auto_open": auto_open,
        "opened": opened,
        "launch_method": launch_method,
    }


def _play_apple_music(query: str, auto_open: bool, browser: str | None = None) -> dict[str, Any]:
    """Resolves and opens Apple Music search for the query."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://music.apple.com/search?term={encoded}"
    opened, launch_method = _open_media_visible(url, browser=browser) if auto_open else (False, None)
    return {
        "status": "success",
        "platform": "apple_music",
        "query": query,
        "title": f"Apple Music: {query}",
        "url": url,
        "auto_open": auto_open,
        "opened": opened,
        "launch_method": launch_method,
    }


def _play_jiosaavn(query: str, auto_open: bool, browser: str | None = None) -> dict[str, Any]:
    """Resolves and opens JioSaavn search for the query."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.jiosaavn.com/search/{encoded}"
    opened, launch_method = _open_media_visible(url, browser=browser) if auto_open else (False, None)
    return {
        "status": "success",
        "platform": "jiosaavn",
        "query": query,
        "title": f"JioSaavn: {query}",
        "url": url,
        "auto_open": auto_open,
        "opened": opened,
        "launch_method": launch_method,
    }


def _is_media_file(path: str) -> bool:
    """Dynamically determines if a path points to audio/video via OS MIME registry."""
    import mimetypes
    mime, _ = mimetypes.guess_type(path)
    return bool(mime and (mime.startswith("audio/") or mime.startswith("video/")))


def _play_local_media(path_or_query: str, auto_open: bool) -> dict[str, Any]:
    """Opens a local audio or video file via the user's default media player."""
    if not _is_media_file(path_or_query):
        raise ValueError(
            f"Target file '{path_or_query}' is not a recognized media (audio/video) file according to system MIME discovery."
        )

    opened = False
    launch_method: str | None = None
    if auto_open:
        if hasattr(os, "startfile"):
            try:
                os.startfile(path_or_query)
                opened = True
                launch_method = "os_startfile"
            except Exception as exc:  # noqa: BLE001
                logger.debug("os.startfile failed for local media '%s': %s", path_or_query, exc)

    return {
        "status": "success",
        "platform": "local",
        "query": path_or_query,
        "title": os.path.basename(path_or_query),
        "url": path_or_query,
        "auto_open": auto_open,
        "opened": opened,
        "launch_method": launch_method,
    }


@tool(
    name="play_song",
    description="Resolves and plays songs or audio queries on YouTube, Spotify, SoundCloud, Apple Music, JioSaavn, or local media via native application or web browser.",
    tags=["media", "music", "audio", "playback"],
)
def play_song(
    query: str,
    platform: str = "youtube",
    auto_open: bool = True,
    browser: str | None = None,
) -> dict[str, Any]:
    """
    Search and play a song on YouTube, Spotify, SoundCloud, Apple Music, JioSaavn, or local media.

    Args:
        query: Song name, artist, query phrase, or local file path (e.g. 'Bohemian Rhapsody Queen').
        platform: Target playback platform ('youtube', 'spotify', 'soundcloud', 'apple_music', 'jiosaavn', 'local', defaults to 'youtube').
        auto_open: If True, automatically launches playback in default browser or application (defaults to True).
        browser: Optional preferred browser executable or name (e.g. 'brave', 'chrome', 'firefox', 'edge').

    Returns:
        Dictionary containing resolution status, platform, title, videoId (for YouTube), url, and playback launch state.

    Raises:
        ValueError: If query is empty or platform is unsupported.
    """
    if not query or not query.strip():
        raise ValueError("Query string cannot be empty for song playback.")

    clean_query = query.strip()
    platform_clean = platform.strip().lower()

    if platform_clean in ("youtube", "yt"):
        return _play_youtube(clean_query, auto_open=auto_open, browser=browser)
    elif platform_clean in ("spotify", "spot"):
        return _play_spotify(clean_query, auto_open=auto_open, browser=browser)
    elif platform_clean in ("soundcloud", "sc"):
        return _play_soundcloud(clean_query, auto_open=auto_open, browser=browser)
    elif platform_clean in ("apple_music", "applemusic", "apple"):
        return _play_apple_music(clean_query, auto_open=auto_open, browser=browser)
    elif platform_clean in ("jiosaavn", "saavn"):
        return _play_jiosaavn(clean_query, auto_open=auto_open, browser=browser)
    elif platform_clean in ("local", "file", "vlc") or (os.path.exists(clean_query) and _is_media_file(clean_query)):
        return _play_local_media(clean_query, auto_open=auto_open)
    else:
        raise ValueError(
            f"Unsupported platform '{platform}'. Supported platforms: 'youtube', 'spotify', 'soundcloud', 'apple_music', 'jiosaavn', 'local'."
        )
