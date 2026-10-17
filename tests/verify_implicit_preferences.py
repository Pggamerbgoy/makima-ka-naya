"""
tests/verify_implicit_preferences.py — Comprehensive Verification for Step 39:
Autonomous Implicit User Preference & Habit Learning (Post-Turn Reflection).
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Reconfigure stdout for utf-8 on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from makima.config import BackendConfig
from makima.core.engine import HermesAgentEngine
from makima.memory.reflection import ImplicitPreferenceLearner
from makima.memory.state import StateMemory
from makima.provider.adapters.base import BaseProvider, Message, ProviderResponse


class MockEngineProvider(BaseProvider):
    def __init__(self, responses: Optional[List[str]] = None) -> None:
        super().__init__(config=BackendConfig(adapter="openai_compatible", provider="mock", model="mock-fast"))
        self.responses = list(responses or ["Done!"])
        self.calls = 0
        self.last_system_prompt = ""

    async def generate(
        self,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> ProviderResponse:
        self.calls += 1
        self.last_system_prompt = system_prompt or ""
        reply = self.responses.pop(0) if self.responses else "OK."
        return ProviderResponse(
            content=reply,
            model="mock-fast",
            finish_reason="stop",
            latency_ms=1.5,
        )

    async def stream(self, *args, **kwargs):
        res = await self.generate(*args, **kwargs)
        yield res.content


async def run_all_tests():
    print("=" * 70)
    print("🚀 Running Implicit Preference Learner Verification Tests")
    print("=" * 70)

    temp_dir = Path(tempfile.mkdtemp(prefix="makima_test_pref_"))
    try:
        sm = StateMemory(data_dir=temp_dir)
        learner = ImplicitPreferenceLearner(state_memory=sm, enable_llm_reflection=False)

        # -------------------------------------------------------------------
        # Test 1: Direct Heuristic Extraction
        # -------------------------------------------------------------------
        print("\n[Stage 1] Testing Direct Heuristic Extraction...")
        test_cases = [
            ("No, don't use Chrome, use Brave instead", "Prefers Brave instead of Chrome"),
            ("I prefer dark mode in all editors", "Prefers dark mode in all editors"),
            ("Always format files before saving", "Always format files before saving"),
            ("Never delete the production database", "Never delete the production database"),
            ("From now on, give brief summaries", "Instruction: give brief summaries"),
            ("My name is Alex", "Name is Alex"),
        ]

        for user_msg, expected in test_cases:
            extracted = learner.extract_heuristically(user_msg)
            print(f"  Input: '{user_msg}' -> Extracted: '{extracted}'")
            assert extracted == expected, f"Expected '{expected}', got '{extracted}'"

        print("✅ Stage 1 Passed: All direct heuristic patterns extracted accurately.")

        # -------------------------------------------------------------------
        # Test 2: Transient Task Command Filtering (Negative Cases)
        # -------------------------------------------------------------------
        print("\n[Stage 2] Testing Transient Command Filtering (Should NOT extract)...")
        transient_cases = [
            "click button 2",
            "read tests/test_smoke.py",
            "what is 10 + 20?",
            "terminate process 1024",
            "close the active window",
            "scroll down by 500 pixels",
        ]

        for trans_msg in transient_cases:
            res = learner.extract_heuristically(trans_msg)
            print(f"  Input: '{trans_msg}' -> Extracted: {res}")
            assert res is None, f"Expected None for transient command '{trans_msg}', but got '{res}'"

        print("✅ Stage 2 Passed: Transient tasks correctly ignored.")

        # -------------------------------------------------------------------
        # Test 3: Deduplication Against USER.md
        # -------------------------------------------------------------------
        print("\n[Stage 3] Testing Deduplication Logic...")
        # Currently default profile has: Communication Style: Direct, concise, technical
        assert learner.is_already_known("Communication Style: Direct, concise") is True
        assert learner.is_already_known("Prefers dark mode in all editors") is False
        print("✅ Stage 3 Passed: Deduplication successfully identifies existing profile items.")

        # -------------------------------------------------------------------
        # Test 4: Autonomous Persistence via learn_from_turn
        # -------------------------------------------------------------------
        print("\n[Stage 4] Testing Autonomous Persistence to USER.md...")
        learned = await learner.learn_from_turn(
            user_message="I prefer using Firefox browser",
            assistant_response="I will use Firefox from now on.",
        )
        assert learned == "Prefers Firefox browser"
        profile_content = sm.read_user_profile()
        assert "Prefers Firefox browser" in profile_content
        print("  USER.md updated with:", learned)

        # Repeating the same turn should be deduplicated
        learned_dup = await learner.learn_from_turn(
            user_message="I prefer using Firefox browser",
            assistant_response="Understood.",
        )
        assert learned_dup is None, "Duplicate preference must return None!"
        print("  Duplicate attempt correctly ignored (returned None).")
        print("✅ Stage 4 Passed: Autonomous persistence and deduplication verified.")

        # -------------------------------------------------------------------
        # Test 5: End-to-End HermesAgentEngine Integration & Background Execution
        # -------------------------------------------------------------------
        print("\n[Stage 5] Testing End-to-End HermesAgentEngine Integration...")
        mock_provider = MockEngineProvider(["Certainly! I will use Brave instead."])
        engine = HermesAgentEngine(
            state_memory=sm,
            preference_learner=learner,
            enable_implicit_learning=True,
        )
        # Mock router execute_with_fallback directly
        async def mock_execute(**kwargs):
            return await mock_provider.generate(
                messages=kwargs.get("messages", []),
                system_prompt=kwargs.get("system_prompt"),
            )
        engine.router.execute_with_fallback = mock_execute  # type: ignore

        # Run turn with correction
        result = await engine.run(
            prompt="No, don't use Chrome, use Brave instead",
            session_id="test_pref_session",
        )
        assert result.completed is True
        print(f"  Engine finished turn. Result: '{result.content}'")

        # Wait for all background tasks to complete
        if engine._background_tasks:
            await asyncio.gather(*engine._background_tasks)

        # Verify USER.md has the newly learned preference
        updated_profile = sm.read_user_profile()
        print("  Updated USER.md content snippet:\n" + "\n".join(updated_profile.splitlines()[-3:]))
        assert "Prefers Brave instead of Chrome" in updated_profile

        # Now run a second turn to confirm system prompt auto-injection
        mock_provider.responses.append("Here is the search result.")
        result2 = await engine.run(
            prompt="Search for Python tutorials",
            session_id="test_pref_session",
        )
        assert result2.completed is True
        assert "Prefers Brave instead of Chrome" in mock_provider.last_system_prompt
        print("✅ Stage 5 Passed: Learned preference automatically injected into subsequent turn's system prompt!")

        print("\n" + "=" * 70)
        print("🎉 ALL 5 IMPLICIT PREFERENCE VERIFICATION STAGES PASSED SUCCESSFULLY!")
        print("=" * 70)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
