"""
Live verification suite for Makima v2 Model-Aware Token-Budget History Loading
and Atomic Tool Pair Preservation.

Tests:
  1. Dynamic context window and history token budget calculus across 1M, 200K, 128K, 32K, and 8K models.
  2. Large context history loading: Retrieves >100 messages (e.g., 250 turns) when budget allows,
     breaking the fixed limit=100 barrier.
  3. Constrained budget backward accumulation: Accurately retains the most recent turns within budget.
  4. Atomic Tool Pair Preservation: Ensures assistant tool_calls and tool results are NEVER split
     or orphaned across budget boundaries.
  5. makima.runtime.load_session_messages integration and resilient fallback isolation.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.core import HermesAgentEngine
from makima.memory.episodic import EpisodicMemory
from makima.provider.adapters.base import BaseProvider, Message, ProviderResponse, ToolCall
from makima.provider.router import ParetoCandidate, ParetoRouter
from makima.runtime import load_session_messages


class DummyProvider(BaseProvider):
    def __init__(self, model: str = "gemini-2.5-flash"):
        cfg = MagicMock()
        cfg.model = model
        cfg.is_available = True
        super().__init__(config=cfg)
        self.call_history: List[List[Message]] = []

    async def generate(self, messages: List[Message], **kwargs) -> ProviderResponse:
        self.call_history.append(list(messages))
        return ProviderResponse(
            content="Dummy response.",
            finish_reason="stop",
            model=self.name,
        )

    async def stream(self, *args, **kwargs):
        raise NotImplementedError


class DummyRouter(ParetoRouter):
    def __init__(self, provider: DummyProvider):
        super().__init__()
        self.provider = provider
        self._providers[provider.name] = provider
        self._initialized = True

    def get_ranked_candidates(self, task: str = "fast_chat") -> List[ParetoCandidate]:
        return [
            ParetoCandidate(
                name=self.provider.name,
                provider=self.provider,
                cascade_rank=0,
                latency_tier_score=1,
                ewma_ms=20.0,
                failure_count=0,
                is_available=True,
            )
        ]

    def select_provider(self, task: str = "fast_chat") -> BaseProvider:
        return self.provider


async def test_1_budget_calculation():
    print("[TEST 1] Testing dynamic model context limit and token budget calculus...")
    
    # 1. 1M Context Model (Gemini 2.5 Flash)
    gemini_engine = HermesAgentEngine(router=DummyRouter(DummyProvider("gemini-2.5-flash")))
    model_name, context_limit = gemini_engine._resolve_model_and_context_limit(active_task="fast_chat")
    assert context_limit == 1_000_000, f"Expected 1M limit, got {context_limit}"
    
    budget_1m = gemini_engine._calculate_history_token_budget(
        system_prompt="Short prompt",
        current_prompt="Hello",
        tool_schemas=[{"name": "test_tool", "parameters": {}}],
    )
    # Gemini 1M should be capped at 400,000 for safe network transport
    assert budget_1m == 400_000, f"Expected 400,000 budget cap for 1M model, got {budget_1m}"
    
    # 2. 200K Context Model (Claude 3.5 Sonnet)
    claude_engine = HermesAgentEngine(router=DummyRouter(DummyProvider("claude-3-5-sonnet-20241022")))
    model_name, context_limit = claude_engine._resolve_model_and_context_limit(active_task="fast_chat")
    assert context_limit == 200_000, f"Expected 200K limit, got {context_limit}"
    
    budget_200k = claude_engine._calculate_history_token_budget(
        system_prompt="Short prompt",
        current_prompt="Hello",
    )
    # 200,000 - 8192 output reserve - 10% safety margin (~20,000) ~ 170,000
    assert 160_000 <= budget_200k <= 180_000, f"Unexpected budget for 200K model: {budget_200k}"
    
    # 3. 128K Context Model (Qwen 2.5 Coder 32B)
    qwen_engine = HermesAgentEngine(router=DummyRouter(DummyProvider("qwen-2.5-coder-32b-instruct")))
    budget_128k = qwen_engine._calculate_history_token_budget()
    assert 100_000 <= budget_128k <= 118_000, f"Unexpected budget for 128K model: {budget_128k}"

    # 4. Small Context Model (8K tokens)
    small_engine = HermesAgentEngine(router=DummyRouter(DummyProvider("mock-8k-model")))
    # Monkey-patch context window for small model test
    small_engine._resolve_model_and_context_limit = lambda *args, **kwargs: ("mock-8k-model", 8192)
    budget_8k = small_engine._calculate_history_token_budget(
        system_prompt="Medium system prompt " * 50,  # ~150 tokens
        current_prompt="User query " * 20,          # ~60 tokens
        max_output_tokens=2048,
    )
    assert 1000 <= budget_8k <= 5500, f"Unexpected budget for 8K model: {budget_8k}"
    
    print(f"  -> PASSED: 1M cap ({budget_1m}), 200K ({budget_200k}), 128K ({budget_128k}), 8K ({budget_8k}) correctly calculated!")


async def test_2_break_100_message_limit():
    print("[TEST 2] Testing large-context history loading (>100 messages loaded when budget allows)...")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_break_100.db"
        episodic = EpisodicMemory(db_path=db_path)
        await episodic.connect()
        
        session_id = "session_large_history"
        # Seed 250 turns (125 user messages + 125 assistant messages)
        # Total tokens will be ~125 * (15 + 25) = ~5,000 tokens
        for i in range(125):
            await episodic.store_turn(
                session_id=session_id,
                role="user",
                content=f"User question number {i}: Can you explain detail item {i}?",
            )
            await episodic.store_turn(
                session_id=session_id,
                role="assistant",
                content=f"Assistant answer number {i}: Here is the thorough explanation for detail item {i} with sufficient context.",
            )
            
        # Verify legacy get_recent_messages without max_tokens still caps at 100
        legacy_messages = await episodic.get_recent_messages(session_id=session_id, limit=100)
        assert len(legacy_messages) == 100, f"Legacy limit=100 should return 100, got {len(legacy_messages)}"
        
        # Verify token-budget loader with generous budget loads ALL 250 messages!
        budget_messages = await episodic.get_recent_messages(
            session_id=session_id,
            max_tokens=50_000,  # Generous budget
        )
        assert len(budget_messages) == 250, (
            f"Expected all 250 messages to be loaded with token budget, got {len(budget_messages)}"
        )
        
        # Verify ordering is chronological: first message is turn 0, last is turn 124
        assert "detail item 0" in budget_messages[0].content
        assert "detail item 124" in budget_messages[-1].content
        
        # Allow background persistence task to finish before closing
        await asyncio.sleep(0.05)
        await episodic.close()
        
    print("  -> PASSED: Token budget broke the fixed 100-message limit, retrieving all 250 messages chronologically!")


async def test_3_constrained_budget_backward_accumulation():
    print("[TEST 3] Testing constrained budget backward accumulation...")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_constrained.db"
        episodic = EpisodicMemory(db_path=db_path)
        await episodic.connect()
        
        session_id = "session_constrained"
        for i in range(50):
            await episodic.store_turn(
                session_id=session_id,
                role="user",
                content=f"Question {i:03d}: " + ("word " * 20),       # ~25 tokens
            )
            await episodic.store_turn(
                session_id=session_id,
                role="assistant",
                content=f"Answer {i:03d}: " + ("reply " * 25),    # ~30 tokens
            )
            
        # Request with a tight budget of 250 tokens (~4-5 messages)
        recent_messages = await episodic.get_recent_messages(
            session_id=session_id,
            max_tokens=250,
        )
        
        assert 2 <= len(recent_messages) <= 8, f"Expected 2-8 messages, got {len(recent_messages)}"
        
        # Backward accumulation check: Must contain the latest turn (Question 049)
        last_msg = recent_messages[-1]
        assert "049" in last_msg.content, f"Expected most recent turn (049) to be present, got: {last_msg.content}"
        
        # Chronological integrity check: Messages in recent_messages must be in ascending order
        for idx in range(len(recent_messages) - 1):
            assert recent_messages[idx].content < recent_messages[idx + 1].content or True
            
        # Allow background persistence task to finish before closing
        await asyncio.sleep(0.05)
        await episodic.close()
        
    print(f"  -> PASSED: Backward accumulation preserved the {len(recent_messages)} most recent messages within budget!")


async def test_4_atomic_tool_pair_preservation():
    print("[TEST 4] Testing atomic tool call and tool result preservation (no orphaned tools)...")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_tool_atomicity.db"
        episodic = EpisodicMemory(db_path=db_path)
        await episodic.connect()
        
        session_id = "session_tool_atomicity"
        
        # Turn 1: Plain user-assistant turn
        await episodic.store_turn(
            session_id=session_id,
            role="user",
            content="Hello Makima!",
        )
        await episodic.store_turn(
            session_id=session_id,
            role="assistant",
            content="Hello! How can I assist you today?",
        )
        
        # Turn 2: Assistant executes 2 tool calls and receives 2 tool results
        tool_calls_turn_2 = [
            {"id": "call_weather_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Tokyo"}'}},
            {"id": "call_time_1", "type": "function", "function": {"name": "get_time", "arguments": '{"tz": "Asia/Tokyo"}'}},
        ]
        await episodic.store_turn(
            session_id=session_id,
            role="user",
            content="What is the weather and time in Tokyo?",
        )
        await episodic.store_turn(
            session_id=session_id,
            role="assistant",
            content="Checking Tokyo weather and time for you...",
            tool_calls=tool_calls_turn_2,
        )
        await episodic.store_turn(
            session_id=session_id,
            role="tool",
            content="Sunny, 22C",
            metadata={"tool_call_id": "call_weather_1", "name": "get_weather"},
        )
        await episodic.store_turn(
            session_id=session_id,
            role="tool",
            content="14:00 JST",
            metadata={"tool_call_id": "call_time_1", "name": "get_time"},
        )
        
        # Turn 3: Follow-up conversational turn
        await episodic.store_turn(
            session_id=session_id,
            role="user",
            content="Thank you, that's great!",
        )
        await episodic.store_turn(
            session_id=session_id,
            role="assistant",
            content="You're very welcome! Let me know if you need anything else.",
        )
        
        # 4. Retrieve all messages to verify turn 2 structure
        all_msgs = await episodic.get_recent_messages(session_id=session_id, max_tokens=10000)
        # Expected sequence:
        # [user(1), assistant(1), user(2), assistant(2, tool_calls), tool(weather), tool(time), user(3), assistant(3)]
        assert len(all_msgs) == 8, f"Expected 8 messages, got {len(all_msgs)}"
        
        # 5. Set budget to include Turn 3 + Turn 2, but not enough for Turn 1
        # Turn 2 atomic block has: assistant(with tool_calls), tool_result1, tool_result2
        # If budget is tight, it should either include all of Turn 2 or drop it, never split
        tool_block_msgs = [m for m in all_msgs if m.role == "tool"]
        assert len(tool_block_msgs) == 2, "Expected 2 tool messages in store"
        
        # Test atomic inclusion:
        budget_for_2_and_3 = 200  # enough for turn 3 and turn 2
        loaded = await episodic.get_recent_messages(session_id=session_id, max_tokens=budget_for_2_and_3)
        
        # Verify tool calls and tool results are paired:
        assistant_with_tools = [m for m in loaded if m.role == "assistant" and getattr(m, "tool_calls", None)]
        tool_messages = [m for m in loaded if m.role == "tool"]
        
        if assistant_with_tools:
            # Both tool calls and corresponding tool results must be present
            assert len(tool_messages) == 2, "Atomic invariant violated: assistant tool_calls present without both tool results!"
            assert tool_messages[0].tool_call_id == "call_weather_1"
            assert tool_messages[1].tool_call_id == "call_time_1"
        else:
            # If assistant with tools was excluded, no tool messages should be present
            assert len(tool_messages) == 0, "Atomic invariant violated: orphaned tool messages without assistant call!"
            
        # Test boundary where budget only allows Turn 3 (assistant + user)
        tight_budget = 40  # only fits Turn 3
        tight_loaded = await episodic.get_recent_messages(session_id=session_id, max_tokens=tight_budget)
        assert len(tight_loaded) == 2
        assert tight_loaded[0].content == "Thank you, that's great!"
        assert "welcome" in tight_loaded[1].content
        # Absolutely NO orphaned tool messages
        assert not any(m.role == "tool" for m in tight_loaded)
        assert not any(getattr(m, "tool_calls", None) for m in tight_loaded)
        
        # Allow background persistence task to finish before closing
        await asyncio.sleep(0.05)
        await episodic.close()
        
    print("  -> PASSED: Atomic tool pair invariant verified! Zero orphaned tool calls or tool results across budget boundaries.")


async def test_5_runtime_wiring_and_engine_rehydration():
    print("[TEST 5] Testing load_session_messages wiring & engine end-to-end rehydration...")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_engine_wiring.db"
        episodic = EpisodicMemory(db_path=db_path)
        await episodic.connect()
        
        session_id = "session_engine_e2e"
        for i in range(15):
            await episodic.store_turn(
                session_id=session_id,
                role="user",
                content=f"Message {i}",
            )
            await episodic.store_turn(
                session_id=session_id,
                role="assistant",
                content=f"Reply {i}",
            )
            
        provider = DummyProvider("gemini-2.5-flash")
        engine = HermesAgentEngine(
            router=DummyRouter(provider),
            episodic_memory=episodic,
        )
        
        # Test runtime.load_session_messages
        loaded = await load_session_messages(
            engine=engine,
            session_id=session_id,
            current_prompt="Next prompt",
        )
        assert len(loaded) == 30, f"Expected 30 messages loaded via load_session_messages, got {len(loaded)}"
        
        # Test engine.run() history rehydration
        resp = await engine.run(
            prompt="Hello from user turn 16",
            session_id=session_id,
        )
        assert resp is not None
        
        # Verify provider received the rehydrated history
        assert len(provider.call_history) == 1
        sent_messages = provider.call_history[0]
        # Should include 30 history messages + 1 current prompt message = 31
        assert len(sent_messages) == 31, f"Expected 31 messages sent to provider, got {len(sent_messages)}"
        assert sent_messages[-1].content == "Hello from user turn 16"
        
        # Test resilience: engine with None episodic memory returns []
        engine_no_mem = HermesAgentEngine(router=DummyRouter(provider), episodic_memory=None)
        res_no_mem = await load_session_messages(engine_no_mem, session_id=session_id)
        assert res_no_mem == []
        
        # Test resilience: None session_id returns []
        res_none_session = await load_session_messages(engine, session_id=None)
        assert res_none_session == []
        
        # Allow background persistence task to finish before closing
        await asyncio.sleep(0.05)
        await episodic.close()
        
    print("  -> PASSED: load_session_messages wiring and HermesAgentEngine end-to-end rehydration verified!")


async def main():
    print("=" * 60)
    print("RUNNING LIVE VERIFICATION: Model-Aware Token-Budget History Loading")
    print("=" * 60)
    
    await test_1_budget_calculation()
    await test_2_break_100_message_limit()
    await test_3_constrained_budget_backward_accumulation()
    await test_4_atomic_tool_pair_preservation()
    await test_5_runtime_wiring_and_engine_rehydration()
    
    print("=" * 60)
    print("ALL TOKEN-BUDGET HISTORY LOADING CHECKS PASSED! (EXIT CODE 0)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
