"""
Verification script for Step 9.2: Windows Media Control & Audio Volume.
Tests:
  1. makima.tools.media imports and exports.
  2. Auto-discovery of media tools by ToolRegistry.
  3. Master volume retrieval via get_volume().
  4. Volume setting and clamping via set_volume().
  5. Mute toggle and restoration via toggle_mute().
  6. Media session status introspection via get_media_status().
  7. Media transport command dispatch via control_media().
"""

import asyncio
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.tools import ToolRegistry, get_registry, reset_registry
from makima.tools.media import (
    control_media,
    get_media_status,
    get_volume,
    set_volume,
    toggle_mute,
)


async def test_exports_and_discovery():
    print("\n[TEST 1] Testing exports and ToolRegistry auto-discovery for media tools...")
    reset_registry()
    reg = ToolRegistry(name="test_media_registry")
    count = reg.discover("makima.tools")

    print(f"  Discovered {count} tools in makima.tools.")
    expected_tools = ["control_media", "get_media_status", "get_volume", "set_volume", "toggle_mute"]
    for t_name in expected_tools:
        assert t_name in reg, f"Tool '{t_name}' was not discovered in registry!"
        tool_obj = reg[t_name]
        assert "media" in tool_obj.tags, f"Tool '{t_name}' missing 'media' tag!"

    print("  [PASS] All 5 media tools discovered and registered with correct tags.")


async def test_volume_controls():
    print("\n[TEST 2] Testing master volume retrieval, setting, clamping, and mute toggle...")
    reg = get_registry(auto_discover=True)

    # 1. get_volume
    vol_data = await reg.execute("get_volume", {})
    assert vol_data.get("success") is True, f"get_volume failed: {vol_data}"
    orig_vol = vol_data["volume_percent"]
    orig_mute = vol_data["is_muted"]
    assert 0.0 <= orig_vol <= 100.0, f"Volume out of range: {orig_vol}"
    assert isinstance(orig_mute, bool)
    print(f"  Initial Volume: {orig_vol}%, Muted: {orig_mute}, Device: {vol_data.get('device')}")

    try:
        # 2. set_volume to safe nearby value (+/- 1% to test modification)
        target_vol = max(10.0, min(90.0, orig_vol - 2.0 if orig_vol > 50 else orig_vol + 2.0))
        set_res = await reg.execute("set_volume", {"percent": target_vol})
        assert set_res.get("success") is True, f"set_volume failed: {set_res}"
        assert abs(set_res["volume_percent"] - target_vol) < 2.0
        print(f"  Set Volume to {target_vol}% -> Current: {set_res['volume_percent']}%")

        # 3. test clamping (e.g. 150% -> 100%, -20% -> 0%)
        clamp_high = await reg.execute("set_volume", {"percent": 150.0})
        assert clamp_high["volume_percent"] == 100.0, f"Clamping high failed: {clamp_high}"

        # 4. toggle_mute
        mute_res1 = await reg.execute("toggle_mute", {})
        assert mute_res1.get("success") is True
        assert mute_res1["is_muted"] != orig_mute, "Mute status did not toggle"
        print(f"  Toggled Mute -> New status: {mute_res1['is_muted']}")

        # Toggle back to original mute state
        mute_res2 = await reg.execute("toggle_mute", {})
        assert mute_res2.get("success") is True
        assert mute_res2["is_muted"] == orig_mute, "Mute status did not revert"
        print(f"  Restored Mute -> Original status: {mute_res2['is_muted']}")

    finally:
        # Restore original volume level
        restore_res = await reg.execute("set_volume", {"percent": orig_vol})
        print(f"  Restored original volume: {restore_res.get('volume_percent')}%")


async def test_media_playback_and_status():
    print("\n[TEST 3] Testing media status and transport controls via WinRT...")
    reg = get_registry(auto_discover=True)

    # 1. get_media_status
    status_data = await reg.execute("get_media_status", {})
    assert "active" in status_data
    assert "playback_status" in status_data
    print(f"  Active Session: {status_data['active']}")
    print(f"  Source App: {status_data.get('source_app')}")
    print(f"  Title: {status_data.get('title')}")
    print(f"  Artist: {status_data.get('artist')}")
    print(f"  Status: {status_data.get('playback_status')}")

    # 2. control_media validation
    invalid_res = await reg.execute("control_media", {"action": "invalid_command"})
    assert invalid_res.get("success") is False
    assert "Unsupported media action" in invalid_res.get("error", "")

    # 3. control_media supported command (safe action query)
    # If no session is playing, it gracefully returns success: False or appropriate status
    ctrl_res = await reg.execute("control_media", {"action": "play_pause"})
    print(f"  control_media result: {ctrl_res}")
    assert "success" in ctrl_res
    assert ctrl_res.get("action") == "play_pause"

    print("  [PASS] Media status and transport controls executed gracefully.")


async def main():
    print("=" * 70)
    print("MAKIMA v2 — STEP 9.2: WINDOWS MEDIA & AUDIO VOLUME VERIFICATION")
    print("=" * 70)

    await test_exports_and_discovery()
    await test_volume_controls()
    await test_media_playback_and_status()

    print("\n" + "=" * 70)
    print("ALL MEDIA & AUDIO TOOL CHECKS PASSED (EXIT CODE 0)")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
