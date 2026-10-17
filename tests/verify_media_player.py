"""
Live verification script for Step 31: Fast Song & Media Playback via YouTube / Spotify.
Tests:
  1. YouTube query resolution with YoutubeSearch and auto_open=False.
  2. Spotify search URI and web URL generation with auto_open=False.
  3. Validation errors for empty query or unsupported platform.
  4. ToolRegistry auto-discovery and dynamic execution of play_song.
"""

import asyncio
import sys
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.tools import get_registry, reset_registry
from makima.tools.media import play_song


def test_youtube_resolution():
    print("\n[TEST 1] Testing YouTube query resolution via play_song (auto_open=False)...")
    query = "Never Gonna Give You Up Rick Astley"
    res = play_song(query, platform="youtube", auto_open=False)

    assert isinstance(res, dict), "Result should be a dictionary"
    assert res.get("status") == "success", f"Failed with status: {res.get('status')}"
    assert res.get("platform") == "youtube"
    assert res.get("opened") is False, "auto_open=False must not launch browser"
    assert res.get("auto_open") is False

    # Check YouTube metadata
    video_id = res.get("videoId")
    assert video_id is not None and len(video_id) > 0, "Expected non-empty videoId"
    url = res.get("url")
    assert url.startswith("https://www.youtube.com/watch?v="), f"Invalid YouTube URL: {url}"
    assert video_id in url
    title = res.get("title")
    assert title and len(title) > 0, "Expected non-empty title"

    print("  [PASS] YouTube resolved successfully:")
    print(f"         Title: {title}")
    print(f"         Video ID: {video_id}")
    print(f"         URL: {url}")
    print(f"         Channel: {res.get('channel')}")


def test_spotify_resolution():
    print("\n[TEST 2] Testing Spotify URI and URL resolution (auto_open=False)...")
    query = "Blinding Lights The Weeknd"
    res = play_song(query, platform="spotify", auto_open=False)

    assert isinstance(res, dict)
    assert res.get("status") == "success"
    assert res.get("platform") == "spotify"
    assert res.get("opened") is False, "auto_open=False must not launch application"
    assert res.get("auto_open") is False

    # Check Spotify metadata
    uri = res.get("uri")
    assert uri == "spotify:search:Blinding Lights The Weeknd", f"Invalid Spotify URI: {uri}"
    url = res.get("url")
    assert url.startswith("https://open.spotify.com/search/"), f"Invalid Spotify Web URL: {url}"

    print("  [PASS] Spotify resolved successfully:")
    print(f"         URI: {uri}")
    print(f"         Web URL: {url}")


def test_validation_and_errors():
    print("\n[TEST 3] Testing argument validation and error conditions...")

    # Empty query
    try:
        play_song("", platform="youtube", auto_open=False)
        assert False, "Should raise ValueError for empty query"
    except ValueError as exc:
        assert "empty" in str(exc).lower()
        print(f"  [PASS] Empty query rejected: {exc}")

    # Whitespace only query
    try:
        play_song("   ", platform="youtube", auto_open=False)
        assert False, "Should raise ValueError for whitespace query"
    except ValueError as exc:
        assert "empty" in str(exc).lower()
        print(f"  [PASS] Whitespace query rejected: {exc}")

    # Unsupported platform
    try:
        play_song("Test Query", platform="unsupported_platform", auto_open=False)
        assert False, "Should raise ValueError for unsupported platform"
    except ValueError as exc:
        assert "unsupported" in str(exc).lower()
        print(f"  [PASS] Unsupported platform rejected: {exc}")


async def test_tool_registry_integration():
    print("\n[TEST 4] Testing ToolRegistry discovery and dynamic execution...")
    reset_registry()
    reg = get_registry(auto_discover=True)

    assert reg.has("play_song"), "play_song was not discovered by ToolRegistry!"
    tool_obj = reg.get("play_song")
    assert tool_obj is not None
    assert "media" in tool_obj.tags
    assert "music" in tool_obj.tags

    # Dynamic execution through registry
    dyn_res = await reg.execute("play_song", {
        "query": "Bohemian Rhapsody Queen",
        "platform": "youtube",
        "auto_open": False,
    })

    assert dyn_res["status"] == "success"
    assert dyn_res["platform"] == "youtube"
    assert dyn_res["opened"] is False
    assert "youtube.com" in dyn_res["url"]
    print(f"  [PASS] play_song dynamically executed via ToolRegistry: {dyn_res['url']}")


async def main():
    print("=" * 75)
    print("MAKIMA v2 — STEP 31: MEDIA PLAYER & SONG RESOLUTION VERIFICATION")
    print("=" * 75)

    test_youtube_resolution()
    test_spotify_resolution()
    test_validation_and_errors()
    await test_tool_registry_integration()

    print("\n" + "=" * 75)
    print("ALL STEP 31 MEDIA PLAYER TESTS PASSED (EXIT CODE 0)")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
