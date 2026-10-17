"""
Live verification script for Phase Step 19: Hermes memory wiring.
Tests:
  1. Memory injection into effective_system_prompt (<memory> section).
  2. Fire-and-forget persistence of user + assistant turns.
  3. No-memory regression (old behavior byte-identical).
  4. Failure isolation (broken memory never breaks run()).
"""

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

# Ensure makima is importable
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.core import HermesAgentEngine
from makima.memory import EpisodicMemory, StateMemory
from makima.provider.adapters.base import BaseProvider, Message, ProviderResponse, ToolCall
from makima.provider.router import ParetoCandidate, ParetoRouter


# -----------------------------------------------------------------------------
# Mock Provider / Router (reuse verify_engine.py pattern)
# -----------------------------------------------------------------------------

class MockHermesProvider(BaseProvider):
    """Predictable mock provider adapter with system_prompt capture."""

    def __init__(self, responses: Optional[List[ProviderResponse]] = None):
        mock_cfg = MagicMock()
        mock_cfg.model = "mock-hermes-v2"
        mock_cfg.is_available = True
        super().__init__(config=mock_cfg)
        self.responses = list(responses or [])
        self.call_history: List[List[Message]] = []
        self.captured_system_prompts: List[Optional[str]] = []

    def queue_response(self, response: ProviderResponse) -> None:
        self.responses.append(response)

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> ProviderResponse:
        self.call_history.append(list(messages))
        self.captured_system_prompts.append(system_prompt)
        if not self.responses:
            return ProviderResponse(
                content="Default mock response.",
                finish_reason="stop",
                model=self.name,
            )
        return self.responses.pop(0)

    async def stream(self, *args, **kwargs):
        raise NotImplementedError("Stream not used in this test.")


class MockRouter(ParetoRouter):
    """Router wrapper injecting mock provider into cascade."""

    def __init__(self, mock_provider: MockHermesProvider):
        super().__init__()
        self.mock_provider = mock_provider
        self._providers["mock"] = mock_provider
        self._initialized = True

    def get_ranked_candidates(self, task: str = "fast_chat") -> List[ParetoCandidate]:
        return [
            ParetoCandidate(
                name="mock",
                provider=self.mock_provider,
                cascade_rank=0,
                latency_tier_score=1,
                ewma_ms=50.0,
                failure_count=0,
                is_available=True,
            )
        ]

    def select_provider(self, task: str = "fast_chat") -> BaseProvider:
        return self.mock_provider


class FakeVectorSearch:
    """Stdlib-only stub matching VectorSearchEngine.search contract."""

    def __init__(self, hits: Optional[List[Dict[str, Any]]] = None):
        self.hits = hits if hits is not None else [
            {"doc_id": "doc1", "content": "pytest is the preferred runner", "distance": 0.12}
        ]
        self.queries: List[str] = []

    async def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        self.queries.append(query)
        return list(self.hits[: max(1, limit)])

    async def add(self, doc_id: str, text: str) -> bool:
        return True


class BrokenEpisodic:
    """Simulates a dead episodic store: every op raises."""

    async def get_recent_messages(self, session_id: str, limit: int = 5):
        raise RuntimeError("simulated episodic read failure")

    async def store_turn(self, *args, **kwargs):
        raise RuntimeError("simulated episodic write failure")


# -----------------------------------------------------------------------------
# Test Cases
# -----------------------------------------------------------------------------

async def test_memory_injection():
    print("[TEST 1] Testing memory injection into system prompt...")
    with tempfile.TemporaryDirectory() as temp_dir:
        state = StateMemory(data_dir=Path(temp_dir) / "state_inject")
        state.append_fact("User prefers pytest over unittest.")

        episodic = EpisodicMemory(":memory:")
        session_id = "inject_session_001"
        await episodic.store_turn(
            session_id=session_id, role="user", content="Earlier the user asked about router cascades."
        )
        await episodic.store_turn(
            session_id=session_id, role="assistant", content="Router cascades were explained."
        )

        vector = FakeVectorSearch()

        provider = MockHermesProvider(
            responses=[
                ProviderResponse(
                    content="Memory-aware answer.", finish_reason="stop", model="mock-hermes-v2"
                )
            ]
        )
        router = MockRouter(provider)
        engine = HermesAgentEngine(router=router, episodic_memory=episodic, state_memory=state, vector_search=vector)

        result = await engine.run(prompt="What test runner do I prefer?", session_id=session_id)
        assert result.completed is True

        # Allow fire-and-forget persist to settle, then clean up.
        await asyncio.sleep(0.5)
        await episodic.close()

        assert provider.captured_system_prompts, "Provider never received a system prompt."
        effective = provider.captured_system_prompts[0] or ""
        assert "<memory>" in effective, "Missing <memory> section in effective system prompt."
        assert "</memory>" in effective, "Missing </memory> close tag."
        assert "pytest over unittest" in effective, "StateMemory fact missing from injection."
        assert "router cascades" in effective, "Episodic recent message missing from injection."
        assert "pytest is the preferred runner" in effective, "Vector hit missing from injection."
        assert "distance=" in effective, "Vector distance missing from injection."

    print("  -> PASSED: <memory> section contains state + episodic + vector context!")


async def test_memory_persistence():
    print("[TEST 2] Testing fire-and-forget turn persistence...")
    episodic = EpisodicMemory(":memory:")
    session_id = "persist_session_002"

    provider = MockHermesProvider(
        responses=[
            ProviderResponse(
                content="Persistence check answer.", finish_reason="stop", model="mock-hermes-v2"
            )
        ]
    )
    router = MockRouter(provider)
    engine = HermesAgentEngine(router=router, episodic_memory=episodic)

    result = await engine.run(prompt="Remember this preference please.", session_id=session_id)
    assert result.completed is True

    # Fire-and-forget: poll briefly until rows land (max ~2s).
    turns: List[Dict[str, Any]] = []
    for _ in range(20):
        await asyncio.sleep(0.1)
        turns = await episodic.get_recent_turns(session_id=session_id, limit=10, order="asc")
        if len(turns) >= 2:
            break

    assert len(turns) >= 2, f"Expected >=2 persisted turns, got {len(turns)}."
    roles = [t["role"] for t in turns]
    assert "user" in roles, f"Missing user turn in {roles}."
    assert "assistant" in roles, f"Missing assistant turn in {roles}."
    assert any("Remember this preference" in (t["content"] or "") for t in turns if t["role"] == "user")

    assistant_turns = [t for t in turns if t["role"] == "assistant"]
    assert assistant_turns, "No assistant turn persisted."
    meta = assistant_turns[-1].get("metadata") or {}
    assert "tool_calls_count" in meta, f"Metadata missing tool_calls_count: {meta}."
    assert "model_used" in meta, f"Metadata missing model_used: {meta}."
    assert "latency_ms" in meta, f"Metadata missing latency_ms: {meta}."

    # FTS index should also find the prompt text.
    fts_hits = await episodic.search_fts(query="Remember this preference", session_id=session_id)
    assert len(fts_hits) >= 1, "FTS search did not find persisted prompt."

    await episodic.close()
    print("  -> PASSED: user + assistant turns persisted with metadata!")


async def test_no_memory_regression():
    print("[TEST 3] Testing no-memory regression (old behavior unchanged)...")
    provider = MockHermesProvider(
        responses=[
            ProviderResponse(
                content="Plain answer, no memory.", finish_reason="stop", model="mock-hermes-v2"
            )
        ]
    )
    router = MockRouter(provider)
    engine = HermesAgentEngine(router=router)

    assert engine.episodic is None
    assert engine.state is None
    assert engine.vector is None

    result = await engine.run(prompt="What is 2 + 2?")
    assert result.completed is True
    assert result.turn_count == 1, f"Expected 1 turn, got {result.turn_count}."
    assert result.tool_calls_executed == 0
    assert result.content == "Plain answer, no memory."
    assert result.finish_reason == "stop"

    effective = provider.captured_system_prompts[0] or ""
    assert "<memory>" not in effective, "Memory section must not appear without session_id."
    assert effective == HermesAgentEngine.DEFAULT_SYSTEM_PROMPT

    print("  -> PASSED: engine without memory behaves exactly as before!")


async def test_failure_isolation():
    print("[TEST 4] Testing failure isolation (broken memory never breaks run)...")
    broken = BrokenEpisodic()
    provider = MockHermesProvider(
        responses=[
            ProviderResponse(
                content="Resilient answer despite broken memory.",
                finish_reason="stop",
                model="mock-hermes-v2",
            )
        ]
    )
    router = MockRouter(provider)
    engine = HermesAgentEngine(router=router, episodic_memory=broken)

    # Broken read path must not raise.
    result = await engine.run(prompt="Hello with broken memory.", session_id="broken_session_004")
    assert result.completed is True
    assert "Resilient answer" in result.content

    # Give the fire-and-forget persist task a chance to fail silently.
    await asyncio.sleep(0.3)

    # Broken state object must not raise either.
    class BrokenState:
        def format_prompt_injection(self):
            raise RuntimeError("simulated state failure")

    engine2 = HermesAgentEngine(router=router, episodic_memory=broken, state_memory=BrokenState())
    provider.queue_response(
        ProviderResponse(
            content="Second resilient answer.", finish_reason="stop", model="mock-hermes-v2"
        )
    )
    result2 = await engine2.run(prompt="Hello again.", session_id="broken_session_005")
    assert result2.completed is True
    assert "Second resilient answer" in result2.content
    await asyncio.sleep(0.3)

    print("  -> PASSED: broken episodic/state isolated, run() never raised!")


# -----------------------------------------------------------------------------
# Main Test Runner
# -----------------------------------------------------------------------------

async def main():
    print("=" * 60)
    print("RUNNING LIVE VERIFICATION: Hermes engine memory wiring (Step 19)")
    print("=" * 60)

    await test_memory_injection()
    await test_memory_persistence()
    await test_no_memory_regression()
    await test_failure_isolation()

    print("=" * 60)
    print("ALL ENGINE MEMORY VERIFICATION CHECKS PASSED! (EXIT CODE 0)")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
        sys.exit(0)
    except Exception as e:
        print(f"\nVERIFICATION SUITE FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
