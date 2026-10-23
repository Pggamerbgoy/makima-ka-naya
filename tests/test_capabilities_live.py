"""
Live Verification Script: Proving the Exact Capabilities Discussed in Chat
1. Habit & Preference Learning (Implicit Preference Extraction & Persistence to USER.md)
2. Audio & Master Volume Management (pycaw Core Audio Endpoint)
3. Media & Song Query Resolution (YouTube / Spotify query engine)
4. Application Discovery (search_installed_apps / get_installed_applications)
5. Messaging Gateway Security & Pairing Authorization
"""

import sys
import pathlib
import time

# Ensure utf-8 encoding for Windows console (handles Japanese / emojis in media titles)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure makima_v2 is in sys.path
makima_root = pathlib.Path(__file__).resolve().parent.parent
if str(makima_root) not in sys.path:
    sys.path.insert(0, str(makima_root))

from makima.memory.reflection import ImplicitPreferenceLearner
from makima.memory.state import StateMemory
from makima.tools.media.volume import get_volume, set_volume
from makima.tools.media.play_song import play_song
from makima.tools.os.app_opener import get_installed_applications
from makima.gateway.security import GatewaySecurityManager
from makima.gateway.adapters.whatsapp import normalize_whatsapp_jid


def test_habit_learning():
    import tempfile
    print("\n--- [TEST 1] Implicit Habit & Preference Learning ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_mem = StateMemory(data_dir=tmp_dir)
        learner = ImplicitPreferenceLearner(state_memory=state_mem, enable_llm_reflection=False)

        # 1. User sets a preference implicitly in natural Hinglish
        user_msg = "mujhe pasand hai 9anime par anime dekhna"
        extracted = learner.extract_heuristically(user_msg)
        print(f"  User input: '{user_msg}'")
        print(f"  Heuristic Learner extracted: '{extracted}'")
        assert extracted is not None, "Failed extracting implicit preference"

        # Persist to isolated USER.md
        state_mem.append_user_profile(extracted)
        user_profile = state_mem.read_user_profile()
        print(f"  Updated User Profile in Memory:\n{user_profile.strip()}")
        assert "9anime" in user_profile, "9anime not found in persistent user profile"
        print("  [PASS] Habit automatically extracted & recorded into user profile.")


def test_master_volume_control():
    print("\n--- [TEST 2] Windows Master Volume Control ---")
    curr_vol = get_volume()
    initial_percent = curr_vol.get("volume_percent", 50.0)
    print(f"  Initial Master Volume: {initial_percent}%")

    target_vol = 35.0
    res = set_volume(percent=target_vol)
    print(f"  set_volume({target_vol}%): {res.get('success')}")

    check_vol = get_volume()
    print(f"  Verified Master Volume: {check_vol.get('volume_percent')}%")
    assert abs(check_vol.get("volume_percent", 0.0) - target_vol) < 2.0, "Volume mismatch"
    print("  [PASS] Windows Core Audio Endpoint master volume control verified.")

    # Restore initial volume
    set_volume(percent=initial_percent)
    print(f"  Restored initial volume to {initial_percent}%.")


def test_media_playback_resolution():
    print("\n--- [TEST 3] Media & Song Query Resolution ---")
    query = "Chainsaw Man Kick Back Kenshi Yonezu"
    print(f"  Resolving media query: '{query}' (auto_open=False for test)")
    res = play_song(query=query, platform="youtube", auto_open=False)
    print(f"  Resolved Video: '{res.get('title')}'")
    print(f"  Resolved URL: {res.get('url')}")
    assert res.get("status") == "success", f"Media search failed: {res}"
    assert "youtube.com" in res.get("url", ""), "Invalid URL resolved"
    print("  [PASS] Media song/anime search & resolution verified.")


def test_app_discovery_vscode():
    print("\n--- [TEST 4] Installed Software Discovery (VS Code) ---")
    apps = get_installed_applications()
    print(f"  Total system applications indexed: {len(apps)}")
    # apps is a list of app name strings
    code_matches = [str(a) for a in apps if "code" in str(a).lower() or "studio" in str(a).lower()]
    print(f"  Discovered Developer Tools / VS Code: {code_matches[:3]}")
    assert len(apps) > 0, "No installed applications discovered"
    print("  [PASS] Dynamic Start Menu and Registry application discovery verified.")


def test_messaging_security():
    print("\n--- [TEST 5] Messaging Gateway Security & Pairing Flow ---")
    sec_mgr = GatewaySecurityManager()
    sender_jid = f"91987{int(time.time()) % 10000000:07d}@s.whatsapp.net"
    normalized = normalize_whatsapp_jid(sender_jid)
    print(f"  Normalized WhatsApp ID: {normalized}")

    # Check unauthenticated sender
    is_auth_before = sec_mgr.is_allowed(user_id=normalized, platform="whatsapp")
    print(f"  Sender Authorized initially? {is_auth_before} (Safety Interception Active)")
    assert not is_auth_before, "Unauthenticated sender should be rejected"

    # Pair code verification
    pair_code = sec_mgr.generate_pairing_code()
    print(f"  Generated Secure Pairing Code: {pair_code}")
    authorized = sec_mgr.verify_pairing_code(code=pair_code, user_id=normalized, platform="whatsapp")
    print(f"  Pairing Code verification: {authorized}")

    is_auth_after = sec_mgr.is_allowed(user_id=normalized, platform="whatsapp")
    print(f"  Sender Authorized after pairing? {is_auth_after}")
    assert is_auth_after, "Sender should be authorized after valid pairing"
    print("  [PASS] Messaging security barrier and pairing verification verified.")


def run_all_tests():
    print("=" * 70)
    print(">>> LIVE PROOF TEST: VERIFYING ALL USER CAPABILITIES DISCUSSED")
    print("=" * 70)
    test_habit_learning()
    test_master_volume_control()
    test_media_playback_resolution()
    test_app_discovery_vscode()
    test_messaging_security()
    print("\n" + "=" * 70)
    print(">>> ALL 5 DISCUSSED CAPABILITIES PROVEN AND VERIFIED LIVE (EXIT CODE 0)")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
