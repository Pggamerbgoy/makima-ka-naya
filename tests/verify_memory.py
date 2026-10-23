"""
Live verification script for Phase 3 Step 10: Dual-Tier Memory Engine.
Files verified:
  - makima/memory/state.py (StateMemory)
  - makima/memory/episodic.py (EpisodicMemory)
  - makima/memory/__init__.py

Tests:
  1. StateMemory default templates creation, reading, and XML/Markdown prompt formatting.
  2. StateMemory fact appending (categorized & general), in-place fact updating, and deletion.
  3. EpisodicMemory connection with automatic SQLite WAL mode ('wal').
  4. EpisodicMemory turn persistence across multiple sessions with tool_calls and metadata.
  5. EpisodicMemory chronological recent turns reconstruction and canonical Message conversion.
  6. EpisodicMemory FTS5 full-text keyword retrieval and session scoping.
  7. EpisodicMemory session listing, count tracking, and clean session deletion.
  8. In-memory (:memory:) context manager lifecycle test.
  9. Zero-hardcoding dynamic path verification.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

# Ensure makima is importable
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.memory import StateMemory, EpisodicMemory
from makima.provider.adapters.base import Message, ToolCall


# -----------------------------------------------------------------------------
# Test 1 & 2: StateMemory Tests
# -----------------------------------------------------------------------------

def test_state_memory():
    print("\n[TEST 1] Testing StateMemory default templates and prompt injection...")
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir) / "state_test"
        state = StateMemory(data_dir=state_dir)

        # 1. Verify default templates were created
        assert (state_dir / "MEMORY.md").is_file(), "MEMORY.md was not created"
        assert (state_dir / "USER.md").is_file(), "USER.md was not created"

        user_profile = state.read_user_profile()
        memory_facts = state.read_memory_facts()
        assert "User Profile & Persona" in user_profile, f"Unexpected profile: {user_profile[:60]}"
        assert "Long-Term Facts" in memory_facts, f"Unexpected facts: {memory_facts[:60]}"

        # 2. Verify prompt injection formatting
        md_injection = state.format_prompt_injection(tag_format=False)
        assert "User Profile & Persona" in md_injection
        assert "Long-Term Facts" in md_injection
        assert "---" in md_injection

        xml_injection = state.format_prompt_injection(tag_format=True)
        assert "<user_profile>" in xml_injection
        assert "</user_profile>" in xml_injection
        assert "<memory_facts>" in xml_injection
        assert "</memory_facts>" in xml_injection
        print("  -> PASSED: Default templates & dynamic prompt injection verified!")

        print("\n[TEST 2] Testing StateMemory fact appending, updating, and extraction...")
        # 3. Append general fact
        state.append_fact("User prefers dark mode and minimal logging.")
        facts = state.get_facts_list()
        assert any("dark mode" in f for f in facts), "General fact not found in facts list"

        # 4. Append categorized fact
        state.append_fact("Ollama model qwen2.5-coder:7b is preferred for offline code generation.", category="Models")
        updated_facts_text = state.read_memory_facts()
        assert "### Models" in updated_facts_text
        assert "qwen2.5-coder:7b" in updated_facts_text

        # 5. In-place update fact
        replaced = state.update_fact(
            search_text="dark mode",
            new_fact="User strictly requires high-contrast dark mode and JSON formatted logs.",
        )
        assert replaced is True, "Expected update_fact to return True"
        facts_after_update = state.get_facts_list()
        assert any("high-contrast dark mode" in f for f in facts_after_update), "Updated fact not found"
        assert not any(f == "User prefers dark mode and minimal logging." for f in facts_after_update)

        # 6. Delete fact
        deleted = state.delete_fact(search_text="high-contrast dark mode")
        assert deleted is True, "Expected delete_fact to return True"
        facts_after_delete = state.get_facts_list()
        assert not any("high-contrast dark mode" in f for f in facts_after_delete)

        # 7. Update user profile
        custom_profile = "# Custom Developer Profile\n- Name: Alice\n- Role: Principal AI Architect"
        state.update_user_profile(custom_profile)
        assert "Alice" in state.read_user_profile()
        print("  -> PASSED: StateMemory fact appending, updating, deleting, and profile updates verified!")


# -----------------------------------------------------------------------------
# Test 3 - 8: EpisodicMemory Async Tests
# -----------------------------------------------------------------------------

async def test_episodic_memory_async():
    print("\n[TEST 3] Testing EpisodicMemory SQLite WAL mode...")
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test_state" / "test_history.db"
        mem = EpisodicMemory(db_path=db_path)

        # Connect and check journal mode
        await mem.connect()
        journal_mode = await mem.get_journal_mode()
        assert journal_mode == "wal", f"Expected WAL mode, got '{journal_mode}'"
        print(f"  -> PASSED: SQLite initialized with WAL mode ({journal_mode.upper()}) at {db_path.name}")

        print("\n[TEST 4] Testing turn persistence with tool_calls and metadata...")
        session_a = "session_alpha_101"
        session_b = "session_beta_202"

        # Turn 0: User query
        t0_id = await mem.store_turn(
            session_id=session_a,
            role="user",
            content="Can you optimize the ParetoRouter cascade order?",
            timestamp=1000.0,
        )
        assert t0_id > 0

        # Turn 1: Assistant calling a tool
        tool_call_payload = [
            ToolCall(
                id="call_991",
                name="benchmark_cascade",
                arguments={"cascade": "fast_chat", "timeout": 15},
            )
        ]
        t1_id = await mem.store_turn(
            session_id=session_a,
            role="assistant",
            content="Checking current latency metrics for the fast_chat cascade.",
            tool_calls=tool_call_payload,
            timestamp=1001.0,
            metadata={"model": "groq/llama-3.3-70b-versatile", "latency_ms": 142.5},
        )
        assert t1_id > t0_id

        # Turn 2: Tool response
        t2_id = await mem.store_turn(
            session_id=session_a,
            role="tool",
            content='{"status": "ok", "fastest": "groq", "ewma_ms": 138.2}',
            timestamp=1002.0,
        )
        assert t2_id > t1_id

        # Turn 3: Assistant final answer
        t3_id = await mem.store_turn(
            session_id=session_a,
            role="assistant",
            content="Groq is running with 138.2ms EWMA. The cascade order is optimal.",
            timestamp=1003.0,
        )
        assert t3_id > t2_id

        # Insert a turn in session_b
        tb0_id = await mem.store_turn(
            session_id=session_b,
            role="user",
            content="What is the weather in Tokyo?",
            timestamp=2000.0,
        )
        assert tb0_id > 0
        print("  -> PASSED: Multi-turn conversations persisted across distinct sessions!")

        print("\n[TEST 5] Testing chronological recent turns and canonical Message reconstruction...")
        # Get recent 3 turns in session A (chronological order)
        recent_turns = await mem.get_recent_turns(session_id=session_a, limit=3, order="asc")
        assert len(recent_turns) == 3, f"Expected 3 turns, got {len(recent_turns)}"
        assert recent_turns[0]["turn_index"] == 1
        assert recent_turns[1]["turn_index"] == 2
        assert recent_turns[2]["turn_index"] == 3

        # Verify tool_calls parsed from JSON
        t1_data = recent_turns[0]
        assert isinstance(t1_data["tool_calls"], list)
        assert t1_data["tool_calls"][0]["name"] == "benchmark_cascade"
        assert t1_data["metadata"]["model"] == "groq/llama-3.3-70b-versatile"

        # Verify canonical Message reconstruction
        messages = await mem.get_recent_messages(session_id=session_a, limit=10)
        assert len(messages) == 4
        assert isinstance(messages[0], Message)
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"
        assert messages[1].tool_calls is not None
        assert messages[1].tool_calls[0].id == "call_991"
        assert messages[2].role == "tool"
        print("  -> PASSED: Chronological turns and canonical Message models reconstructed correctly!")

        print("\n[TEST 6] Testing FTS5 full-text keyword retrieval...")
        # Search query matching turn in session_a
        fts_results_a = await mem.search_fts(query="ParetoRouter cascade")
        assert len(fts_results_a) > 0, "FTS query for 'ParetoRouter cascade' returned 0 results"
        assert any("optimize the ParetoRouter" in r["content"] for r in fts_results_a)

        # Search with session scoping
        fts_session_scoped = await mem.search_fts(query="Tokyo", session_id=session_a)
        assert len(fts_session_scoped) == 0, "Session A should not match Tokyo from Session B"

        fts_session_b = await mem.search_fts(query="Tokyo", session_id=session_b)
        assert len(fts_session_b) == 1, "Session B should match Tokyo"
        assert "Tokyo" in fts_session_b[0]["content"]
        print("  -> PASSED: FTS5 keyword retrieval & session filtering verified!")

        print("\n[TEST 7] Testing session listing and clean deletion...")
        count_a = await mem.get_session_turn_count(session_a)
        assert count_a == 4, f"Expected 4 turns, got {count_a}"

        sessions = await mem.list_sessions()
        session_ids = [s["session_id"] for s in sessions]
        assert session_a in session_ids
        assert session_b in session_ids

        # Delete session_b
        deleted_count = await mem.delete_session(session_b)
        assert deleted_count == 1, f"Expected 1 deleted turn for session B, got {deleted_count}"

        # Verify session_a is intact
        assert await mem.get_session_turn_count(session_a) == 4
        assert await mem.get_session_turn_count(session_b) == 0

        # Close database
        await mem.close()
        print("  -> PASSED: Session metadata tracking and clean deletion verified!")

    print("\n[TEST 8] Testing in-memory (:memory:) async context manager lifecycle...")
    async with EpisodicMemory(":memory:") as in_memory_store:
        t_id = await in_memory_store.store_turn(
            session_id="ephemeral_session",
            role="user",
            content="Ephemeral in-memory test turn",
        )
        assert t_id == 1
        turns = await in_memory_store.get_recent_turns("ephemeral_session")
        assert len(turns) == 1
        assert turns[0]["content"] == "Ephemeral in-memory test turn"
    print("  -> PASSED: EpisodicMemory(:memory:) context manager verified!")


# -----------------------------------------------------------------------------
# Test 9: Zero-Hardcoding Path Resolution Test
# -----------------------------------------------------------------------------

def test_zero_hardcoding():
    print("\n[TEST 9] Verifying zero-hardcoding dynamic path guarantees...")
    state_default = StateMemory()
    home = Path.home()
    expected_default_dir = home / ".makima"
    assert state_default.data_dir == expected_default_dir, f"Mismatch: {state_default.data_dir}"
    assert state_default.memory_path == expected_default_dir / "MEMORY.md"
    assert state_default.user_path == expected_default_dir / "USER.md"

    episodic_default = EpisodicMemory()
    expected_sqlite_path = expected_default_dir / "state" / "history.db"
    assert episodic_default.db_path == expected_sqlite_path, f"Mismatch: {episodic_default.db_path}"
    print(f"  -> PASSED: Dynamic paths resolved safely to {expected_default_dir} without hardcoding!")


# -----------------------------------------------------------------------------
# Main Test Runner
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("RUNNING LIVE VERIFICATION: Makima v2 Dual-Tier Memory Engine (Step 10)")
    print("=" * 70)

    try:
        test_state_memory()
        asyncio.run(test_episodic_memory_async())
        test_zero_hardcoding()

        print("\n" + "=" * 70)
        print("ALL DUAL-TIER MEMORY VERIFICATION SUITES PASSED! (EXIT CODE 0)")
        print("=" * 70)
        sys.exit(0)
    except Exception as e:
        print(f"\nVERIFICATION SUITE FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
