"""
tests/verify_preference_memory.py — Verification Suite for Hermes-Style User Preference & Memory Tools.

Tests:
  1. Tool discovery and schema synthesis in ToolRegistry.
  2. Saving user preference to USER.md via `remember_user_preference`.
  3. Reading back user profile via `get_user_profile`.
  4. Saving knowledge fact to MEMORY.md via `remember_fact` with categories.
  5. Reading back memory facts via `get_memory_facts`.
  6. Dynamic prompt injection verification via `StateMemory.format_prompt_injection`.
  7. Forgetting user preference via `forget_user_preference`.
  8. Forgetting memory fact via `forget_fact`.
  9. Edge case handling (empty inputs, nonexistent items).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from makima.memory.state import StateMemory
from makima.tools.memory import (
    forget_fact,
    forget_user_preference,
    get_memory_facts,
    get_user_profile,
    remember_fact,
    remember_user_preference,
)
from makima.tools.registry import get_registry, reset_registry


def test_preference_and_memory_tools():
    print("=" * 70)
    print("RUNNING VERIFICATION: Hermes-Style User Preference & Memory Tools")
    print("=" * 70)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tmp_path = Path(tmp_dir)
        user_file = tmp_path / "USER.md"
        memory_file = tmp_path / "MEMORY.md"

        # Patch StateMemory instance to test isolated in tmp_dir
        StateMemory(data_dir=tmp_path)
        assert user_file.exists()
        assert memory_file.exists()

        # Monkeypatch StateMemory in makima.tools.memory to use our isolated tmp_path
        import makima.tools.memory as mem_mod

        original_StateMemory = mem_mod.StateMemory
        mem_mod.StateMemory = lambda: StateMemory(data_dir=tmp_path)

        try:
            # -------------------------------------------------------------
            # Stage 1: Tool Registry Discovery
            # -------------------------------------------------------------
            print("\n[STAGE 1] Testing ToolRegistry discovery and schemas...")
            reset_registry()
            reg = get_registry(auto_discover=True)

            assert reg.has("remember_user_preference")
            assert reg.has("remember_fact")
            assert reg.has("forget_user_preference")
            assert reg.has("forget_fact")
            assert reg.has("get_user_profile")
            assert reg.has("get_memory_facts")

            pref_tool = reg.get("remember_user_preference")
            assert pref_tool is not None
            pref_schema = pref_tool.to_schema(format="openai")
            assert pref_schema["function"]["name"] == "remember_user_preference"
            assert "preference" in pref_schema["function"]["parameters"]["properties"]
            print("  [PASS] All 6 memory tools discovered and registered in ToolRegistry.")

            # -------------------------------------------------------------
            # Stage 2: Save User Preferences
            # -------------------------------------------------------------
            print("\n[STAGE 2] Testing remember_user_preference...")
            res1 = remember_user_preference("Prefers VS Code with dark theme and PowerShell")
            assert res1["success"] is True
            assert "dark theme" in res1["message"]

            res2 = remember_user_preference("Favorite music streaming service is Spotify")
            assert res2["success"] is True

            user_content = user_file.read_text(encoding="utf-8")
            assert "Prefers VS Code with dark theme and PowerShell" in user_content
            assert "Favorite music streaming service is Spotify" in user_content
            print("  [PASS] Successfully persisted user preferences into USER.md.")

            # -------------------------------------------------------------
            # Stage 3: Read User Profile
            # -------------------------------------------------------------
            print("\n[STAGE 3] Testing get_user_profile...")
            profile_res = get_user_profile()
            assert profile_res["success"] is True
            assert "dark theme" in profile_res["content"]
            assert "Spotify" in profile_res["content"]
            print("  [PASS] Successfully retrieved user profile via get_user_profile.")

            # -------------------------------------------------------------
            # Stage 4: Save Memory Facts
            # -------------------------------------------------------------
            print("\n[STAGE 4] Testing remember_fact with categories...")
            fact1 = remember_fact("User's primary project is Makima v2 autonomous desktop agent", category="Projects")
            assert fact1["success"] is True
            assert fact1["category"] == "Projects"

            fact2 = remember_fact("Never install deprecated pyautogui, always use SendInput", category="Engineering Guidelines")
            assert fact2["success"] is True

            mem_content = memory_file.read_text(encoding="utf-8")
            assert "### Projects" in mem_content
            assert "Makima v2 autonomous desktop agent" in mem_content
            assert "### Engineering Guidelines" in mem_content
            assert "SendInput" in mem_content
            print("  [PASS] Successfully stored categorized facts into MEMORY.md.")

            # -------------------------------------------------------------
            # Stage 5: Read Memory Facts
            # -------------------------------------------------------------
            print("\n[STAGE 5] Testing get_memory_facts...")
            facts_res = get_memory_facts()
            assert facts_res["success"] is True
            assert facts_res["count"] >= 2
            assert any("SendInput" in f for f in facts_res["facts"])
            print(f"  [PASS] Retrieved {facts_res['count']} facts via get_memory_facts.")

            # -------------------------------------------------------------
            # Stage 6: Dynamic Prompt Injection Verification
            # -------------------------------------------------------------
            print("\n[STAGE 6] Testing prompt injection integration...")
            isolated_sm = StateMemory(data_dir=tmp_path)
            injection = isolated_sm.format_prompt_injection(tag_format=True)
            assert "<user_profile>" in injection
            assert "dark theme" in injection
            assert "<memory_facts>" in injection
            assert "Makima v2" in injection
            print("  [PASS] Prompt injection block seamlessly contains user preferences and memory facts.")

            # -------------------------------------------------------------
            # Stage 7: Forget User Preference & Fact
            # -------------------------------------------------------------
            print("\n[STAGE 7] Testing forget_user_preference and forget_fact...")
            del_pref = forget_user_preference("Spotify")
            assert del_pref["success"] is True
            updated_user = user_file.read_text(encoding="utf-8")
            assert "Spotify" not in updated_user
            assert "dark theme" in updated_user

            del_fact = forget_fact("SendInput")
            assert del_fact["success"] is True
            updated_mem = memory_file.read_text(encoding="utf-8")
            assert "SendInput" not in updated_mem

            # Try to delete nonexistent item
            no_del = forget_fact("NonexistentFactXYZ")
            assert no_del["success"] is False
            print("  [PASS] Successfully removed targeted preferences and facts with clean degradation.")

            # -------------------------------------------------------------
            # Stage 8: Edge Cases
            # -------------------------------------------------------------
            print("\n[STAGE 8] Testing empty input edge cases...")
            assert remember_user_preference("   ")["success"] is False
            assert remember_fact("")["success"] is False
            assert forget_user_preference("")["success"] is False
            assert forget_fact("  ")["success"] is False
            print("  [PASS] Clean edge case validation passed.")

            print("\n" + "=" * 70)
            print("ALL 8 STAGES OF PREFERENCE & MEMORY VERIFICATION PASSED!")
            print("=" * 70)

        finally:
            mem_mod.StateMemory = original_StateMemory


if __name__ == "__main__":
    test_preference_and_memory_tools()
