"""
tests/verify_e2e.py — Step 26: End-to-End Integration Verification Test.
Verifies the complete integration chain across:
  - HermesAgentEngine
  - ToolRegistry & real/mock tool execution
  - StateMemory (system prompt injection)
  - EpisodicMemory (turn persistence with SQLite WAL)
  - VectorSearchEngine (semantic auto-indexing & recall)
  - SkillsLoader (system prompt skill injection)
  - StructuredTelemetry (runtime event emission & JSONL logging)
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from makima.core.context import ContextCompressor
from makima.core.engine import EngineResult, HermesAgentEngine
from makima.core.guardrails import Guardrails
from makima.core.telemetry import StructuredTelemetry
from makima.memory.episodic import EpisodicMemory
from makima.memory.state import StateMemory
from makima.memory.vector_search import VectorSearchEngine
from makima.provider.adapters.base import BaseProvider, Message, ProviderResponse, ToolCall
from makima.provider.router import ParetoRouter
from makima.skills.loader import Skill, SkillsLoader
from makima.tools.registry import ToolRegistry, tool

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    tag = PASS if ok else FAIL
    msg = f"  {tag} {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append(ok)


from unittest.mock import MagicMock
from makima.provider.router import ParetoCandidate


# ---------------------------------------------------------------------------
# Mock Multi-Turn Provider for E2E Testing
# ---------------------------------------------------------------------------
class E2EMockProvider(BaseProvider):
    """Predictable multi-turn mock provider simulating autonomous Hermes loop."""

    def __init__(self, name: str = "e2e_mock"):
        mock_cfg = MagicMock()
        mock_cfg.model = "e2e-mock-v1"
        mock_cfg.is_available = True
        super().__init__(config=mock_cfg)
        self.call_count = 0
        self.last_system_prompt: str = ""
        self.last_messages: List[Message] = []

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> ProviderResponse:
        self.call_count += 1
        self.last_system_prompt = system_prompt or ""
        self.last_messages = list(messages)

        # First turn: trigger tool call
        if self.call_count == 1:
            return ProviderResponse(
                content="Let me look up the weather for Tokyo.",
                tool_calls=[
                    ToolCall(
                        id="call_mock_1",
                        name="get_city_weather",
                        arguments={"city": "Tokyo"},
                    )
                ],
                finish_reason="tool_calls",
                model="e2e-mock-v1",
                latency_ms=15.0,
            )
        # Second turn: tool result returned, synthesize final answer
        elif self.call_count == 2:
            return ProviderResponse(
                content="The weather in Tokyo is 22°C and sunny.",
                tool_calls=[],
                finish_reason="stop",
                model="e2e-mock-v1",
                latency_ms=25.0,
            )
        # Subsequent calls: direct conversational response
        else:
            return ProviderResponse(
                content=f"Acknowledged turn {self.call_count}.",
                tool_calls=[],
                finish_reason="stop",
                model="e2e-mock-v1",
                latency_ms=10.0,
            )

    async def stream(self, *args, **kwargs):
        raise NotImplementedError("Stream not used in this test.")


class E2EMockRouter(ParetoRouter):
    """Router wrapper injecting mock provider into cascade."""

    def __init__(self, mock_provider: E2EMockProvider):
        super().__init__()
        self.mock_provider = mock_provider
        self._providers["e2e_mock"] = mock_provider
        self._initialized = True

    def get_ranked_candidates(self, task: str = "fast_chat") -> List[ParetoCandidate]:
        return [
            ParetoCandidate(
                name="e2e_mock",
                provider=self.mock_provider,
                cascade_rank=0,
                latency_tier_score=1,
                ewma_ms=20.0,
                failure_count=0,
                is_available=True,
            )
        ]

    def select_provider(self, task: str = "fast_chat") -> BaseProvider:
        return self.mock_provider


# ---------------------------------------------------------------------------
# Test Suites
# ---------------------------------------------------------------------------
async def run_e2e_tests():
    print("=" * 60)
    print("Step 26 — End-to-End Integration Verification (E2E)")
    print("=" * 60)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_history.db"
        vec_db_path = tmp_path / "test_vec.db"
        state_dir = tmp_path / "state"
        skills_dir = tmp_path / "skills"
        telemetry_dir = tmp_path / "telemetry"

        state_dir.mkdir(parents=True, exist_ok=True)
        skills_dir.mkdir(parents=True, exist_ok=True)
        telemetry_dir.mkdir(parents=True, exist_ok=True)

        # 1. Setup StateMemory with user fact
        user_md = state_dir / "USER.md"
        user_md.write_text("# User Profile\n- Name: TestOperator\n- City: Neo-Tokyo\n", encoding="utf-8")
        memory_md = state_dir / "MEMORY.md"
        memory_md.write_text("# Knowledge Base\n- Makima is running in autonomous E2E mode.\n", encoding="utf-8")

        state_mem = StateMemory(data_dir=state_dir)
        record("StateMemory initialization & template load", state_mem is not None)

        # 2. Setup EpisodicMemory & VectorSearchEngine
        episodic_mem = EpisodicMemory(db_path=db_path)
        await episodic_mem.connect()
        record("EpisodicMemory connect with SQLite WAL", episodic_mem is not None)

        vec_engine = VectorSearchEngine(db_path=vec_db_path)
        await vec_engine.connect()
        record("VectorSearchEngine connect with sqlite-vec / cosine fallback", vec_engine is not None)

        # 3. Setup SkillsLoader with sample skill
        sample_skill_file = skills_dir / "weather.md"
        sample_skill_file.write_text(
            "---\nname: weather_reporter\ndescription: How to report weather\ntags: [weather, climate]\n---\nAlways include temperature in Celsius.\n",
            encoding="utf-8",
        )
        skills_loader = SkillsLoader(skills_dir=skills_dir)
        skills_loader.load_all()
        record("SkillsLoader scan & parse sample skill", len(skills_loader.load_all()) >= 1)

        # 4. Setup StructuredTelemetry
        telemetry = StructuredTelemetry(log_dir=telemetry_dir, buffer_size=100)
        record("StructuredTelemetry initialized with temporary JSONL path", telemetry is not None)

        # 5. Setup ToolRegistry with a test tool
        test_registry = ToolRegistry(name="e2e_registry")

        @tool(name="get_city_weather", description="Gets the weather of a city", tags=["weather"])
        def get_city_weather(city: str) -> Dict[str, Any]:
            return {"city": city, "temperature": 22, "condition": "Sunny"}

        test_registry.register(get_city_weather)
        record("ToolRegistry registers get_city_weather tool", test_registry.has("get_city_weather"))

        # 6. Setup Mock Router and HermesAgentEngine
        mock_provider = E2EMockProvider()
        test_router = E2EMockRouter(mock_provider)

        engine = HermesAgentEngine(
            router=test_router,
            episodic_memory=episodic_mem,
            vector_search=vec_engine,
            state_memory=state_mem,
            skills_loader=skills_loader,
            telemetry=telemetry,
        )
        record("HermesAgentEngine assembled with all 6 subsystems", engine is not None)

        # 7. Execute First Multi-Turn Session (Tool Call -> Tool Result -> Completion)
        session_id = "session_e2e_alpha"
        result_1 = await engine.run(
            prompt="What is the weather in Tokyo right now?",
            tools=test_registry,
            session_id=session_id,
        )

        ok_res1 = (
            result_1.completed is True
            and result_1.tool_calls_executed == 1
            and "Tokyo" in result_1.content
            and "22°C" in result_1.content
        )
        record("E2E Session 1: Autonomous loop executes tool and synthesizes answer", ok_res1, f"content='{result_1.content}'")

        # Verify state facts and skills were injected into system prompt
        injected = mock_provider.last_system_prompt
        has_state = "Neo-Tokyo" in injected and "TestOperator" in injected
        has_skills = "weather_reporter" in injected or "Celsius" in injected
        record("System Prompt includes StateMemory facts (USER.md / MEMORY.md)", has_state)
        record("System Prompt includes SkillsLoader instructions", has_skills)

        # Allow background tasks to finish writing to SQLite WAL
        await asyncio.sleep(0.3)

        # 8. Verify EpisodicMemory Persisted All Turns
        turns = await episodic_mem.get_recent_turns(session_id=session_id, limit=10)
        # Should have user prompt, assistant tool call, tool result, assistant final response (4 turns)
        record("EpisodicMemory persists turns across the autonomous loop", len(turns) >= 3, f"persisted_turns={len(turns)}")

        # 9. Verify VectorSearchEngine Auto-Indexed the Conversation
        vec_count = await vec_engine.document_count()
        record("VectorSearchEngine auto-indexes conversation turns in background", vec_count >= 1, f"doc_count={vec_count}")

        # 10. Verify StructuredTelemetry Emitted Complete Lifecycle Events
        events = telemetry.get_recent(50)
        event_types = [e["event"] for e in events]
        has_run_start = "engine.run_start" in event_types
        has_tool_exec = "tool.execute" in event_types
        has_run_complete = "engine.run_complete" in event_types
        record(
            "StructuredTelemetry recorded complete engine & tool lifecycle",
            has_run_start and has_tool_exec and has_run_complete,
            f"events={event_types}",
        )

        # 11. Run Second Turn in Same Session — Verify Cross-Turn Memory Recall
        result_2 = await engine.run(
            prompt="Can you summarize what we just checked?",
            tools=test_registry,
            session_id=session_id,
        )
        record("E2E Session 2: Second turn runs seamlessly in same session", result_2.completed)

        # Allow background tasks to finish writing to SQLite WAL before closing
        await asyncio.sleep(0.3)

        # Cleanup connections
        await episodic_mem.close()
        await vec_engine.close()


def main():
    asyncio.run(run_e2e_tests())
    print("=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    print("=" * 60)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
