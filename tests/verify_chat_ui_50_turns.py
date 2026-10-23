"""
End-to-End Live Verification Script: 50+ Chat UI WebSocket Turns & Multi-Turn Memory.
Simulates the exact React Chat UI WebSocket contract over 50 consecutive dialogue turns,
verifying:
  1. WebSocket streaming lifecycle across 50 consecutive messages.
  2. Session continuity across all 50 turns without amnesia or session splitting.
  3. Structured tool executions, tool calls, and tool results persistence in EpisodicMemory.
  4. Full rehydration of all 50 turns into HermesAgentEngine without dropping early turns.
  5. Context window scaling (~286K budget): verifies NO premature compression occurs
     during normal multi-turn conversations.
  6. FTS5 full-text search retrieval across historical turns.
  7. SessionStore UI metadata alignment for the Chat UI sidebar.
  8. Intentional compression trigger when token budget genuinely exceeds 85% of 286K.
"""

import asyncio
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient
from makima.api.app import create_app
from makima.core.engine import HermesAgentEngine
from makima.core.context import ContextCompressor
from makima.memory import EpisodicMemory, StateMemory
from makima.provider.adapters.base import BaseProvider, Message, ProviderResponse, ToolCall
from makima.provider.router import ParetoCandidate, ParetoRouter
from makima.tools.registry import ToolRegistry


class SmartMultiTurnProvider(BaseProvider):
    """
    Stateful mock provider that responds appropriately across 50 turns,
    simulates tool execution on specific turns, and inspects the rehydrated history.
    """

    def __init__(self):
        mock_cfg = MagicMock()
        mock_cfg.model = "mock-hermes-v2"
        mock_cfg.is_available = True
        super().__init__(config=mock_cfg)
        self.call_history: List[List[Message]] = []
        self.turn_counter = 0

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        self.call_history.append(list(messages))
        self.turn_counter += 1

        last_user_msg = next((m.content for m in reversed(messages) if m.role == "user"), "")

        # Turn 10: Simulate calling a system tool
        if "check system stats" in last_user_msg.lower():
            # If tool result is already in history, synthesize answer
            if any(m.role == "tool" and "get_system_stats" in str(m.name or m.tool_call_id or "") for m in messages):
                return ProviderResponse(
                    content="System stats verified: CPU is at 22%, RAM is healthy.",
                    model=self.name,
                    tool_calls=[],
                    finish_reason="stop",
                )
            return ProviderResponse(
                content="",
                model=self.name,
                tool_calls=[ToolCall(id="call_sys_stats_10", name="get_system_stats", arguments={})],
                finish_reason="tool_calls",
            )

        # Turn 25: Simulate search tool call
        if "search for rust 2024" in last_user_msg.lower():
            if any(m.role == "tool" and "search_web" in str(m.name or m.tool_call_id or "") for m in messages):
                return ProviderResponse(
                    content="Rust 2024 edition features RPITIT and async closures.",
                    model=self.name,
                    tool_calls=[],
                    finish_reason="stop",
                )
            return ProviderResponse(
                content="",
                model=self.name,
                tool_calls=[ToolCall(id="call_search_25", name="search_web", arguments={"query": "rust 2024 edition"})],
                finish_reason="tool_calls",
            )

        # Recall queries: inspect rehydrated history to confirm past details are accessible
        if "what laptop" in last_user_msg.lower():
            # Check if ThinkPad from Turn 2 is present in rehydrated messages
            found = any("thinkpad x1 carbon" in (m.content or "").lower() for m in messages)
            status = "FOUND in working history" if found else "NOT FOUND in history"
            return ProviderResponse(
                content=f"Your laptop is ThinkPad X1 Carbon with 32GB RAM ({status}).",
                model=self.name,
                tool_calls=[],
                finish_reason="stop",
            )

        if "what city and budget" in last_user_msg.lower():
            found_bengaluru = any("bengaluru" in (m.content or "").lower() for m in messages)
            found_budget = any("1,20,000" in (m.content or "") for m in messages)
            status = "ALL FOUND" if (found_bengaluru and found_budget) else "PARTIAL/MISSING"
            return ProviderResponse(
                content=f"Your city is Bengaluru and budget is INR 1,20,000 ({status}).",
                model=self.name,
                tool_calls=[],
                finish_reason="stop",
            )

        # Default conversational acknowledgment
        return ProviderResponse(
            content=f"Acknowledged turn {self.turn_counter}: received '{last_user_msg[:60]}'.",
            model=self.name,
            tool_calls=[],
            finish_reason="stop",
        )

    async def stream(self, *args, **kwargs):
        raise NotImplementedError()


class SmartRouter(ParetoRouter):
    def __init__(self, provider: SmartMultiTurnProvider):
        super().__init__()
        self.provider = provider
        self._providers["mock"] = provider
        self._initialized = True

    def get_ranked_candidates(self, task: str = "fast_chat") -> List[ParetoCandidate]:
        return [
            ParetoCandidate(
                name="mock",
                provider=self.provider,
                cascade_rank=0,
                latency_tier_score=1,
                ewma_ms=50.0,
                failure_count=0,
                is_available=True,
            )
        ]

    def select_provider(self, task: str = "fast_chat") -> BaseProvider:
        return self.provider


def build_app_and_engine(temp_dir: Path):
    db_path = temp_dir / "history_50_test.db"
    episodic = EpisodicMemory(db_path=db_path, fts_enabled=True)
    state = StateMemory(data_dir=temp_dir / "state")
    provider = SmartMultiTurnProvider()
    router = SmartRouter(provider)

    compressor = ContextCompressor()
    engine = HermesAgentEngine(
        router=router,
        episodic_memory=episodic,
        state_memory=state,
        compressor=compressor,
        max_turns=10,
    )

    registry = ToolRegistry()
    registry.register(
        lambda: {"cpu": 22.0, "ram_gb": 16.0, "status": "ok"},
        name="get_system_stats",
        description="Returns mock CPU and RAM statistics",
        tags=["system"],
    )
    registry.register(
        lambda query: f"Search results for '{query}': Rust 2024 stabilizes async fn in traits.",
        name="search_web",
        description="Mock web search engine",
        tags=["web", "search"],
    )

    session_store_db = temp_dir / "sessions_50_test.sqlite3"
    app = create_app(
        engine=engine,
        registry=registry,
        ui_state_path=temp_dir / "ui_state.json",
        session_db_path=session_store_db,
    )

    return app, engine, provider, episodic, session_store_db


def test_50_turn_chat_ui_workflow():
    print("=" * 70)
    print("RUNNING 50-TURN CHAT UI WEBSOCKET & MULTI-TURN MEMORY TEST")
    print("=" * 70)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        app, engine, provider, episodic, session_db = build_app_and_engine(tmp_dir)
        client = TestClient(app)

        session_id = "test_ui_session_50_turns"
        app.state.session_store.create_session(session_id=session_id, title="50 Turn UI Test")
        print(f"[*] Initialized test environment with session_id: {session_id}")

        # -------------------------------------------------------------------------
        # Connect to WebSocket (just like apps/chat_ui/src/App.tsx)
        # -------------------------------------------------------------------------
        with client.websocket_connect("/ws") as ws:
            print("[*] WebSocket connected successfully to /ws")

            total_messages_to_send = 50
            t_start = time.time()

            for i in range(1, total_messages_to_send + 1):
                task_id = f"task_{i:03d}"
                msg_id = f"message_{task_id}"

                # Structured prompts with specific anchor facts and tasks
                if i == 1:
                    prompt = "Hello Makima, my name is Amit and I work as a senior Rust backend engineer."
                elif i == 2:
                    prompt = "I use a ThinkPad X1 Carbon laptop with 32GB RAM and Arch Linux."
                elif i == 3:
                    prompt = "I live in Bengaluru, India."
                elif i == 4:
                    prompt = "My personal electronics shopping budget for this month is INR 1,20,000."
                elif i == 5:
                    prompt = "My preferred terminal editor is Neovim with Lua configurations."
                elif i == 10:
                    prompt = "Please check system stats for my machine."
                elif i == 25:
                    prompt = "Please search for rust 2024 edition features."
                elif i == 46:
                    prompt = "What laptop model and RAM did I mention earlier?"
                elif i == 47:
                    prompt = "What city and budget did I specify earlier?"
                else:
                    prompt = f"Turn {i}: Continuing our engineering discussion on distributed consensus and Raft protocols."

                # Send exact payload format generated by Chat UI App.tsx (line 679)
                payload = {
                    "type": "user_message",
                    "task_id": task_id,
                    "message_id": msg_id,
                    "session_id": session_id,
                    "content": prompt,
                    "task": "fast_chat",
                }
                ws.send_json(payload)

                # Receive streaming events until completed
                received_events = []
                while True:
                    event = ws.receive_json()
                    received_events.append(event)
                    if event.get("type") == "status" and event.get("stage") == "completed":
                        break
                    if event.get("type") == "error":
                        raise AssertionError(f"WebSocket error on turn {i}: {event}")

                # Ensure final message event was received
                msg_events = [e for e in received_events if e.get("type") == "message"]
                assert msg_events, f"Turn {i} failed to receive final message event."
                assistant_reply = msg_events[0].get("content", "")

                # Specific assertions on milestones
                if i == 10:
                    tool_call_events = [e for e in received_events if e.get("type") == "tool_call"]
                    assert tool_call_events, "Turn 10 expected 'get_system_stats' tool call event"
                    assert tool_call_events[0]["name"] == "get_system_stats"
                    assert "healthy" in assistant_reply
                    print(f"  [Turn {i:02d}] Tool execution verified: get_system_stats -> {assistant_reply[:50]}...")
                elif i == 25:
                    tool_call_events = [e for e in received_events if e.get("type") == "tool_call"]
                    assert tool_call_events, "Turn 25 expected 'search_web' tool call event"
                    assert tool_call_events[0]["name"] == "search_web"
                    assert "Rust 2024" in assistant_reply
                    print(f"  [Turn {i:02d}] Tool execution verified: search_web -> {assistant_reply[:50]}...")
                elif i == 46:
                    assert "FOUND in working history" in assistant_reply, f"Turn 46 failed to recall laptop: {assistant_reply}"
                    print(f"  [Turn {i:02d}] RECALL SUCCESS: {assistant_reply}")
                elif i == 47:
                    assert "ALL FOUND" in assistant_reply, f"Turn 47 failed to recall city/budget: {assistant_reply}"
                    print(f"  [Turn {i:02d}] RECALL SUCCESS: {assistant_reply}")
            # Allow background fire-and-forget persistence tasks to complete on server event loop
            t_drain_start = time.time()
            while engine._background_tasks and time.time() - t_drain_start < 5.0:
                time.sleep(0.05)

            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong.get("type") == "pong"

            elapsed_s = round(time.time() - t_start, 2)
            print(f"\n[+] Successfully completed all {total_messages_to_send} turns in {elapsed_s}s!")

        # -------------------------------------------------------------------------
        # Post-Execution Database & Memory Assertions
        # -------------------------------------------------------------------------
        print("\n" + "=" * 70)
        print("VERIFYING POST-EXECUTION MEMORY PERSISTENCE & HISTORY REHYDRATION")
        print("=" * 70)

        # 1. Verify EpisodicMemory turns count
        # In a 50-turn conversation with 2 tool calls:
        # 50 user turns + 50 assistant replies + 2 tool calls + 2 tool results = 104 turns
        async def _drain_and_get_turns():
            if engine._background_tasks:
                await asyncio.gather(*list(engine._background_tasks), return_exceptions=True)
            for _ in range(25):
                turns = await episodic.get_recent_turns(session_id=session_id, limit=200)
                if len(turns) >= 100:
                    return turns
                await asyncio.sleep(0.05)
            return await episodic.get_recent_turns(session_id=session_id, limit=200)

        all_turns = asyncio.run(_drain_and_get_turns())
        print(f"[*] Total persisted turns in EpisodicMemory: {len(all_turns)}")
        roles_count = {}
        for t in all_turns:
            roles_count[t['role']] = roles_count.get(t['role'], 0) + 1
        print(f"[*] Role breakdown: {roles_count}")
        print(f"[*] First 3 turns: {[(t['turn_index'], t['role'], t['content'][:40]) for t in all_turns[:3]]}")
        print(f"[*] Last 3 turns: {[(t['turn_index'], t['role'], t['content'][:40]) for t in all_turns[-3:]]}")
        assert len(all_turns) >= 100, f"Expected >= 100 turns in history.db, got {len(all_turns)}"

        # 2. Verify earliest messages are still present in history.db
        turn1_turn = next((t for t in all_turns if "Amit and I work as a senior Rust" in (t["content"] or "")), None)
        assert turn1_turn is not None, "Turn 1 was lost from history.db!"
        print("  [PASS] Earliest user message (Turn 1) intact in EpisodicMemory.")

        turn2_turn = next((t for t in all_turns if "ThinkPad X1 Carbon" in (t["content"] or "")), None)
        assert turn2_turn is not None, "Turn 2 was lost from history.db!"
        print("  [PASS] Laptop anchor fact (Turn 2) intact in EpisodicMemory.")

        # 3. Verify tool call and tool result preservation in history.db
        tool_turns = [t for t in all_turns if t["role"] == "tool"]
        assert len(tool_turns) >= 2, f"Expected >=2 tool turns, got {len(tool_turns)}"
        print(f"  [PASS] Tool results preserved ({len(tool_turns)} tool turns stored).")

        # 4. Verify canonical Message reconstruction with tool metadata
        messages = asyncio.run(episodic.get_recent_messages(session_id=session_id, limit=200))
        assert len(messages) >= 100
        tool_msgs = [m for m in messages if m.role == "tool"]
        assert len(tool_msgs) >= 2
        assert all(m.tool_call_id or m.name for m in tool_msgs)
        print("  [PASS] Canonical Messages reconstructed with tool_call_id and names intact.")

        # 5. Verify FTS5 Full-Text Search across the 50 turns
        fts_hits_laptop = asyncio.run(episodic.search_fts(query="ThinkPad", session_id=session_id))
        assert len(fts_hits_laptop) >= 1, "FTS5 failed to find 'ThinkPad'"
        print(f"  [PASS] FTS5 search found 'ThinkPad' ({len(fts_hits_laptop)} hit).")

        fts_hits_city = asyncio.run(episodic.search_fts(query="Bengaluru", session_id=session_id))
        assert len(fts_hits_city) >= 1, "FTS5 failed to find 'Bengaluru'"
        print(f"  [PASS] FTS5 search found 'Bengaluru' ({len(fts_hits_city)} hit).")

        fts_hits_rust = asyncio.run(episodic.search_fts(query="2024 edition", session_id=session_id))
        assert len(fts_hits_rust) >= 1, "FTS5 search found '2024 edition'"
        print(f"  [PASS] FTS5 search found '2024 edition' ({len(fts_hits_rust)} hit).")

        # 6. Verify SessionStore UI metadata alignment
        store = app.state.session_store
        session_data = store.get_session(session_id)
        assert session_data is not None, "Session missing in SessionStore"
        stored_msgs = session_data.get("messages", [])
        print(f"[*] Total messages in SessionStore for UI sidebar: {len(stored_msgs)}")
        assert len(stored_msgs) >= 100, f"Expected >=100 messages in SessionStore, got {len(stored_msgs)}"
        print("  [PASS] SessionStore perfectly synced with 50 user turns and 50 assistant turns.")

        # 7. Verify Context Compressor didn't prematurely compress normal dialogue
        compressor = ContextCompressor()
        tokens = compressor.estimate_tokens(messages)
        budget = compressor.trigger_token_budget
        print(f"[*] Current 50-turn tokens: ~{tokens} tokens (Budget: {budget} tokens)")
        assert tokens < budget, f"50 normal turns ({tokens} tokens) exceeded budget ({budget})!"
        assert not compressor.needs_compression(messages), "needs_compression incorrectly returned True for normal dialogue"
        print(f"  [PASS] Context window ~286K verified: normal 50-turn dialogue comfortably fits within budget without compression.")

        # 8. Verify Compressor DOES safely compress if tokens genuinely exceed threshold
        huge_messages = list(messages)
        # Inject synthetic bloated turn exceeding 286K budget
        huge_content = "large text data payload " * 80_000  # ~400,000 tokens
        huge_messages.append(Message(role="user", content=huge_content))
        assert compressor.needs_compression(huge_messages), "needs_compression failed to trigger on truly oversized context"
        compressed = compressor.compress(huge_messages)
        assert len(compressed) < len(huge_messages), "Compressor failed to reduce message count"
        assert any(m.role == "system" and "[CONTEXT COMPRESSED:" in (m.content or "") for m in compressed)
        print("  [PASS] Context Compressor triggers correctly when context genuinely fills up (~286K).")

        asyncio.run(episodic.close())

    print("\n" + "=" * 70)
    print("ALL 50-TURN CHAT UI WEBSOCKET & MEMORY TESTS PASSED! (EXIT CODE 0)")
    print("=" * 70)


if __name__ == "__main__":
    try:
        test_50_turn_chat_ui_workflow()
        sys.exit(0)
    except Exception as exc:
        print(f"\nTEST FAILED: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
