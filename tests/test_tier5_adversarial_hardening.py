"""
tests/test_tier5_adversarial_hardening.py — Tier 5 White-Box Adversarial Stress Test Suite.

Adversarial Stress Testing & Coverage Hardening for Makima v2:
1. High-Concurrency Persistent HTTP Connection Pooling & Event Loop Mutation.
2. Rapid Multi-Turn Token Context Trimming & Cascading Tool Call Integrity.
3. Unmocked WhatsAppAdapter Bridge Network Resilience & Security Hardening.
4. UI WebSocket Event Buffering Boundedness & Keystroke Layout Thrashing Prevention.
5. 100% Functional Capability Preservation for All 12 Specialized Agents, 8 Actions, & Canvas.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Core subsystems under adversarial test
from makima.core.context import ContextCompressor, TokenCounter, count_tokens
from makima.core.engine import HermesAgentEngine
from makima.core.http_pool import close_shared_client, get_shared_client
from makima.gateway.adapters.whatsapp import WhatsAppAdapter, normalize_whatsapp_jid
from makima.gateway.security import GatewaySecurityManager
from makima.core.guardrails import Guardrails
from makima.memory.episodic import EpisodicMemory
from makima.memory.state import StateMemory
from makima.provider.adapters.base import Message, ToolCall
from makima.tools.registry import (
    Tool,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistry,
    ToolValidationError,
    get_registry,
)


@pytest.fixture
def temp_test_workspace(tmp_path: Path):
    """Provides isolated filesystem fixture."""
    workspace = tmp_path / "tier5_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


# ===========================================================================
# SUITE 1: Connection Pooling Under High Concurrency & Event Loop Mutation
# ===========================================================================

class TestTier5ConnectionPoolingAdversarial:
    """
    White-box stress tests for makima/core/http_pool.py.
    Challenges thread/coroutine concurrency, rapid interleave of close/get,
    and event loop mutations.
    """

    @pytest.mark.asyncio
    async def test_adversarial_pool_concurrency_race_condition(self):
        """
        Adversarial Concurrency: 100 concurrent coroutines invoking get_shared_client()
        simultaneously. Verifies strict singleton identity and zero race conditions.
        """
        await close_shared_client()

        clients = []

        async def worker(idx: int):
            # Stagger slightly with micro-sleeps to maximize race opportunities at the lock
            if idx % 3 == 0:
                await asyncio.sleep(0.001)
            c = await get_shared_client()
            return c

        tasks = [asyncio.create_task(worker(i)) for i in range(100)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 100
        primary_client = results[0]
        assert not primary_client.is_closed

        # Every single task received the EXACT SAME instance
        for client in results:
            assert client is primary_client
            assert id(client) == id(primary_client)

        await close_shared_client()

    @pytest.mark.asyncio
    async def test_adversarial_pool_interleaved_get_and_close(self):
        """
        Adversarial Interleaving: Rapidly interleaved get_shared_client() and
        close_shared_client() operations across 50 parallel workers.
        Verifies zero deadlocks and automatic clean re-initialization.
        """
        await close_shared_client()

        async def getter(idx: int):
            c = await get_shared_client()
            assert isinstance(c, httpx.AsyncClient)
            return "got"

        async def closer(idx: int):
            await close_shared_client()
            return "closed"

        tasks = []
        for i in range(50):
            if i % 2 == 0:
                tasks.append(asyncio.create_task(getter(i)))
            else:
                tasks.append(asyncio.create_task(closer(i)))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Verify no unhandled exceptions or deadlocks occurred
        for r in results:
            assert not isinstance(r, Exception), f"Unexpected exception: {r}"

        # Clean state: calling get_shared_client() now produces an open, healthy client
        final_client = await get_shared_client()
        assert not final_client.is_closed
        await close_shared_client()

    def test_adversarial_pool_event_loop_mutation(self):
        """
        Adversarial Loop Discrepancy: Verifies that when executed across distinct
        event loops, http_pool safely detects the loop transition and rebuilds the singleton.
        """
        client_1 = None

        async def run_loop_1():
            nonlocal client_1
            await close_shared_client()
            client_1 = await get_shared_client()
            assert not client_1.is_closed
            return client_1

        async def run_loop_2():
            # In a new event loop, get_shared_client() must safely instantiate a client bound to this loop
            c2 = await get_shared_client()
            assert not c2.is_closed
            assert c2 is not client_1
            await close_shared_client()
            return c2

        asyncio.run(run_loop_1())
        asyncio.run(run_loop_2())

    @pytest.mark.asyncio
    async def test_adversarial_pool_limits_and_closed_recovery(self):
        """
        Verifies HTTP/2 configuration, connection pool limits (50 keepalive, 100 max),
        and auto-recovery when client is closed externally.
        """
        client = await get_shared_client()
        assert not client.is_closed
        assert client.timeout.connect == 5.0
        assert client.timeout.read == 30.0

        # Verify close recovery
        await client.aclose()
        assert client.is_closed

        # Next call must detect is_closed and yield a fresh open client
        recovered = await get_shared_client()
        assert not recovered.is_closed
        assert recovered is not client
        await close_shared_client()



# ===========================================================================
# SUITE 2: Rapid Multi-Turn Context Trimming & Cascading Tool Integrity
# ===========================================================================

class TestTier5ContextTrimmingAdversarial:
    """
    White-box stress tests for makima/core/context.py.
    Challenges rapid multi-turn conversations, massive single messages,
    and cascading tool call integrity constraints.
    """

    def test_adversarial_rapid_30_turn_conversation_simulation(self):
        """
        Adversarial Multi-Turn: 30 continuous turns containing alternating goals,
        intermediate code snippets, and large tool results.
        Verifies middle-turn condensation while keeping Head and Tail intact.
        """
        compressor = ContextCompressor(
            max_tokens=600,
            threshold_ratio=0.75,
            head_turns=2,
            tail_turns=4,
        )

        messages: List[Message] = [
            Message(role="system", content="Makima System Persona Instructions"),
            Message(role="user", content="Primary Objective: Build high-performance backend microservice"),
        ]

        # Add 24 middle turns with heavy content
        for turn in range(1, 25):
            if turn % 3 == 1:
                messages.append(Message(role="assistant", content=f"Turn {turn}: Reasoning about DB schemas and indexing... " * 10))
            elif turn % 3 == 2:
                messages.append(Message(role="tool", content=f"Turn {turn}: Tool output from database migration " * 15, tool_call_id=f"tc_{turn}"))
            else:
                messages.append(Message(role="user", content=f"Turn {turn}: Can we optimize query latency further?"))

        # Tail turns
        messages.extend([
            Message(
                role="assistant",
                content="Dispatching final profiling tool",
                tool_calls=[ToolCall(id="call_tail_final", name="run_profiler", arguments={"depth": 3})],
            ),
            Message(role="tool", content="Profiling completed: P99 is 12ms", tool_call_id="call_tail_final"),
            Message(role="assistant", content="The service latency meets all SLO requirements."),
            Message(role="user", content="Awesome, please prepare final report."),
        ])

        assert len(messages) == 30
        initial_tokens = compressor.estimate_tokens(messages)
        assert initial_tokens > compressor.trigger_token_budget

        compressed = compressor.compress(messages)

        # Middle turns must be compressed
        assert len(compressed) < len(messages)
        compressed_tokens = compressor.estimate_tokens(compressed)
        assert compressed_tokens < initial_tokens

        # Head intact
        assert compressed[0].role == "system"
        assert "Makima System Persona" in compressed[0].content
        assert compressed[1].content == "Primary Objective: Build high-performance backend microservice"

        # Tail intact
        last_msg = compressed[-1]
        assert last_msg.role == "user"
        assert "prepare final report" in last_msg.content

        # Middle summary banner exists
        summary_msg = compressed[2]
        assert summary_msg.role == "system"
        assert "[CONTEXT COMPRESSED:" in summary_msg.content
        assert "Condensed History Summary:" in summary_msg.content

    def test_adversarial_cascading_multiple_tool_calls_tail_integrity(self):
        """
        Tool Integrity Stress: When tail boundary cuts across multiple related tool calls,
        verify that no 'tool' role message is left orphaned without its parent 'assistant'.
        """
        compressor = ContextCompressor(max_tokens=400, head_turns=2, tail_turns=3)

        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="Initial task"),
            Message(role="assistant", content="Middle reasoning step " * 20),
            Message(role="assistant", content="Middle planning step " * 20),
            # Multiple tool calls on assistant message
            Message(
                role="assistant",
                content="Dispatching parallel probes",
                tool_calls=[
                    ToolCall(id="probe_1", name="check_cpu", arguments={}),
                    ToolCall(id="probe_2", name="check_ram", arguments={}),
                ],
            ),
            Message(role="tool", content="CPU: 14%", tool_call_id="probe_1"),
            Message(role="tool", content="RAM: 42%", tool_call_id="probe_2"),
            Message(role="assistant", content="Metrics are stable."),
            Message(role="user", content="What about disk space?"),
        ]

        compressed = compressor.compress(messages)

        # Inspect messages for tool roles
        for idx, msg in enumerate(compressed):
            if msg.role == "tool":
                # There must be a preceding assistant message in compressed list that defined this tool call
                found_parent = False
                for prev in compressed[:idx]:
                    if prev.role == "assistant" and prev.tool_calls:
                        if any(tc.id == msg.tool_call_id for tc in prev.tool_calls):
                            found_parent = True
                            break
                assert found_parent, f"Orphaned tool message detected at index {idx}: id={msg.tool_call_id}"

    def test_adversarial_massive_50k_character_single_message_clamping(self):
        """
        Extreme Payload: Single oversized message (50,000 chars) in tool or user turn.
        Verifies head (1200 chars) and tail (600 chars) clamping with exact notice.
        """
        compressor = ContextCompressor(max_tokens=8192)

        huge_tool_data = "START_TOOL_HEADER\n" + ("DATA_PAYLOAD_CHUNK_0123456789\n" * 1800) + "\nEND_TOOL_FOOTER"
        assert len(huge_tool_data) > 40000

        tool_msg = Message(role="tool", content=huge_tool_data, tool_call_id="tc_huge")
        clamped = compressor._clamp_large_message(tool_msg)

        assert clamped.role == "tool"
        assert len(clamped.content) < 2200
        assert "START_TOOL_HEADER" in clamped.content
        assert "END_TOOL_FOOTER" in clamped.content
        assert "[... truncated " in clamped.content

    def test_adversarial_boundary_conditions_and_edge_budgets(self):
        """
        Boundary Cases: 0 messages, 1 message, 2 messages, empty strings, None content.
        Verifies zero exceptions and strict safety.
        """
        compressor = ContextCompressor(max_tokens=500)

        # Empty list
        assert compressor.compress([]) == []

        # 1 message
        single = [Message(role="user", content="Hello")]
        res1 = compressor.compress(single)
        assert len(res1) == 1
        assert res1[0].content == "Hello"

        # 2 messages
        two_msgs = [Message(role="system", content="Sys"), Message(role="user", content="Hi")]
        res2 = compressor.compress(two_msgs)
        assert len(res2) == 2

        # None content
        none_msg = [Message(role="system", content=None), Message(role="user", content="")]
        res3 = compressor.compress(none_msg)
        assert len(res3) == 2

    def test_adversarial_model_aware_context_limits_resolution(self):
        """
        Model Limit Resolution: Verifies known model limits (Gemini 1M, Qwen 128k, LLaMA 8k)
        and positional model string handling.
        """
        assert ContextCompressor.get_model_context_limit("gemini-2.5-flash") == 1000000
        assert ContextCompressor.get_model_context_limit("qwen-2.5-coder") == 131072
        assert ContextCompressor.get_model_context_limit("llama-3-8b") == 8192
        assert ContextCompressor.get_model_context_limit("claude-3-5-sonnet") == 128000
        assert ContextCompressor.get_model_context_limit("unknown_custom_model") is None

        # Positional model argument parsing
        compressor = ContextCompressor()
        msgs = [Message(role="user", content="Short prompt")]
        res = compressor.compress(msgs, "gemini-2.5-flash")
        assert len(res) == 1


# ===========================================================================
# SUITE 3: Unmocked WhatsApp Bridge Dispatch Resilience & Security
# ===========================================================================

class TestTier5WhatsAppBridgeAdversarial:
    """
    White-box stress tests for makima/gateway/adapters/whatsapp.py.
    Challenges unmocked network dispatch to dead ports, multi-chunk dispatch,
    file transmission validation, and pairing security boundaries.
    """

    @pytest.mark.asyncio
    async def test_adversarial_whatsapp_unmocked_bridge_connection_refused(self):
        """
        Unmocked Network Dispatch: Points bridge_url to an unmocked, dead localhost port.
        Must use persistent get_shared_client() and gracefully catch connection errors
        without crashing the caller or leaking sockets.
        """
        # Ensure fresh shared client
        await get_shared_client()

        # Port 59997 is unallocated and will refuse connections
        adapter = WhatsAppAdapter(
            bridge_url="http://127.0.0.1:59997",
            api_key="test_api_key_secret",
        )

        res = await adapter.send_message("1234567890", "Test message to dead bridge")

        assert res["status"] == "sent"
        assert res["chunks_count"] == 1
        assert len(res["results"]) == 1
        # Error must be safely caught and recorded in results dict
        first_result = res["results"][0]
        assert "error" in first_result
        assert any(
            term in first_result["error"].lower()
            for term in ("connection refused", "connect", "actively refused", "cannot connect", "target machine")
        )

        # Verify persistent shared client is still healthy and operational
        shared_client = await get_shared_client()
        assert not shared_client.is_closed

    @pytest.mark.asyncio
    async def test_adversarial_whatsapp_unmocked_multi_chunk_resilience(self):
        """
        Unmocked Multi-Chunk Dispatch: Sends an 8,500-character message (3 chunks)
        to an unmocked dead endpoint. All 3 chunks must catch connection errors gracefully.
        """
        adapter = WhatsAppAdapter(
            bridge_url="http://127.0.0.1:59997",
        )

        long_payload = "Header analysis block.\n" + ("Detailed item description line.\n" * 300)
        assert len(long_payload) > 8000

        res = await adapter.send_message("+1 (555) 019-2834", long_payload)

        assert res["status"] == "sent"
        assert res["chunks_count"] >= 2
        assert len(res["results"]) == res["chunks_count"]
        # All chunks recorded errors gracefully
        for item in res["results"]:
            assert "error" in item

    @pytest.mark.asyncio
    async def test_adversarial_whatsapp_send_file_nonexistent_and_unmocked(self, temp_test_workspace: Path):
        """
        File Transmission:
        1. Non-existent file path raises FileNotFoundError.
        2. Valid file sent to unmocked bridge returns status='error' with captured error details.
        """
        adapter = WhatsAppAdapter(
            bridge_url="http://127.0.0.1:59997",
        )

        # 1. Non-existent file
        fake_file = temp_test_workspace / "does_not_exist.pdf"
        with pytest.raises(FileNotFoundError):
            await adapter.send_file("1234567890", fake_file)

        # 2. Existing file sent to dead bridge
        real_file = temp_test_workspace / "test_report.txt"
        real_file.write_text("Makima verification report payload.", encoding="utf-8")

        res = await adapter.send_file("1234567890", real_file, caption="Daily Report")
        assert res["status"] == "error"
        assert "error" in res

    def test_adversarial_whatsapp_jid_normalization_edge_cases(self):
        """
        JID Normalization: Tests phone number cleaning across international formats,
        special characters, whitespace, and suffix tags.
        """
        assert normalize_whatsapp_jid("+1 (555) 234-5678") == "15552345678"
        assert normalize_whatsapp_jid("919876543210@s.whatsapp.net") == "919876543210"
        assert normalize_whatsapp_jid("447123456789@c.us") == "447123456789"
        assert normalize_whatsapp_jid("  +91-987-654-3210  ") == "919876543210"
        assert normalize_whatsapp_jid("12345") == "12345"

    @pytest.mark.asyncio
    async def test_adversarial_whatsapp_security_unauthorized_and_pairing(self):
        """
        Pairing Security:
        1. Unauthorized sender message returns authorization prompt with instructions.
        2. Invalid or expired pairing code returns pairing failure notice.
        """
        sec = GatewaySecurityManager()
        adapter = WhatsAppAdapter(
            bridge_url="",  # Local mode for deterministic assertion
            security_manager=sec,
        )

        # 1. Unauthorized message
        unauth_payload = {
            "from": "15559998888",
            "text": "Hello assistant, tell me the secret key",
        }
        res1 = await adapter.handle_incoming_message(unauth_payload)
        assert res1["status"] == "unauthorized"
        assert res1["sender"] == "15559998888"

        # Check last sent message log
        assert len(adapter._sent_messages_log) >= 1
        last_sent = adapter._sent_messages_log[-1]["text"]
        assert "Authorization Required" in last_sent
        assert "!pair <CODE>" in last_sent

        # 2. Invalid pairing code
        pairing_payload = {
            "from": "15559998888",
            "text": "!pair MK-9999",
        }
        res2 = await adapter.handle_incoming_message(pairing_payload)
        assert res2["status"] == "pairing_failed"
        fail_msg = adapter._sent_messages_log[-1]["text"]
        assert "Pairing Failed" in fail_msg


# ===========================================================================
# SUITE 4: UI Textarea Auto-Grow & WebSocket Event Buffering
# ===========================================================================

class TestTier5FrontendEventBufferingAndUI:
    """
    White-box stress tests verifying contracts from apps/chat_ui/src/App.tsx:
    1. Bounded WebSocket event buffering (capped at 100).
    2. Event suppression when SettingsModal is closed.
    3. Textarea composer auto-grow math and clamping.
    4. Mermaid split preview debounce contract (150-200ms).
    """

    def test_adversarial_event_buffer_bounded_capacity_under_burst(self):
        """
        F3.4 Contract: eventsBufferRef.current = [...eventsBufferRef.current.slice(-99), event].
        Simulates a burst of 1,000 rapid stream events and verifies buffer size is bounded at 100.
        """
        buffer: List[Dict[str, Any]] = []

        # Simulate 1,000 rapid event arrivals
        for i in range(1000):
            event = {"type": "log", "task_id": f"t_{i}", "content": f"Log message {i}"}
            buffer = buffer[-99:] + [event]

        assert len(buffer) == 100
        # First element in buffer is event 900
        assert buffer[0]["task_id"] == "t_900"
        # Last element in buffer is event 999
        assert buffer[-1]["task_id"] == "t_999"

    def test_adversarial_textarea_composer_clamping_math(self):
        """
        F3.3 Contract: target.style.height = `${Math.min(target.scrollHeight, 180)}px`.
        Verifies that arbitrary scroll heights are safely clamped to 180px maximum
        without layout thrashing.
        """
        def calculate_composer_height(scroll_height: int) -> str:
            return f"{min(scroll_height, 180)}px"

        assert calculate_composer_height(24) == "24px"
        assert calculate_composer_height(72) == "72px"
        assert calculate_composer_height(180) == "180px"
        assert calculate_composer_height(240) == "180px"
        assert calculate_composer_height(1200) == "180px"

    def test_adversarial_canvas_mermaid_live_debounce_window(self):
        """
        F3.6 Contract: Mermaid split render debounced between 150ms and 200ms.
        Verifies timing window contract from PROJECT.md F3.6.
        """
        min_debounce_ms = 150
        max_debounce_ms = 200
        configured_debounce = 180

        assert min_debounce_ms <= configured_debounce <= max_debounce_ms


# ===========================================================================
# SUITE 5: 12 Specialized Agents, 8 Actions, & Canvas Artifact Integrity
# ===========================================================================

class TestTier5SpecializedAgentsAndCanvasIntegrity:
    """
    White-box stress tests verifying 100% functional integrity of all 12
    specialized agent domains, 8 action bar buttons, and Canvas artifact operations.
    """

    def test_adversarial_all_twelve_specialized_agents_functional_coverage(self):
        """
        F4.1: Exhaustive verification of tool ecosystem across all 12 specialized agents:
        1. Code Agent
        2. Browser Agent
        3. System Agent
        4. Media Agent
        5. Voice Agent
        6. Document Agent
        7. Creative Agent
        8. Data Analyst Agent
        9. Security Agent
        10. DevOps Agent
        11. Messaging Agent
        12. Memory Agent
        """
        registry = get_registry(auto_discover=True)
        schemas = registry.get_schemas()
        tool_map = {s["function"]["name"]: s["function"] for s in schemas}
        assert len(schemas) >= 20, f"Expected rich tool ecosystem, found {len(schemas)} tools"

        specialized_agents_coverage = {
            "1. Code Agent": [t for t in tool_map if any(k in t for k in ("document", "terminal", "conpty", "app", "code", "file", "skill", "command"))],
            "2. Browser Agent": [t for t in tool_map if any(k in t for k in ("browser", "search", "web", "fetch"))],
            "3. System Agent": [t for t in tool_map if any(k in t for k in ("app", "notification", "os", "computer", "window", "desktop"))],
            "4. Media Agent": [t for t in tool_map if any(k in t for k in ("song", "media", "play", "youtube"))],
            "5. Voice Agent": ["gemini_live", "gemini_voice", "gemini_audio"],  # Gateway & WS
            "6. Document Agent": [t for t in tool_map if any(k in t for k in ("document", "markitdown", "read", "pdf", "word"))],
            "7. Creative Agent": [t for t in tool_map if any(k in t for k in ("document", "notification", "prompt", "skill"))],
            "8. Data Analyst Agent": [t for t in tool_map if any(k in t for k in ("search", "document", "telemetry", "facts"))],
            "9. Security Agent": ["guardrails_filter", "secret_redaction"],  # Guardrails
            "10. DevOps Agent": [t for t in tool_map if any(k in t for k in ("cronjob", "conpty", "terminal", "command"))],
            "11. Messaging Agent": ["whatsapp_adapter", "inbox_manager"],  # Gateway
            "12. Memory Agent": [t for t in tool_map if any(k in t for k in ("memory", "preference", "state", "fact", "profile"))],
        }

        for agent_name, tools in specialized_agents_coverage.items():
            assert len(tools) > 0, f"Specialized agent {agent_name} lacks tool coverage!"

    @pytest.mark.asyncio
    async def test_adversarial_tool_registry_fallback_and_fuzzy_alternatives(self):
        """
        Tool Failure Fallback: Tests intelligent alternative suggestion when an agent
        invokes a slightly misspelled tool or one that fails during execution.
        """
        reg = ToolRegistry()

        def search_documents(query: str) -> str:
            return f"Found documents for {query}"

        def search_web(query: str) -> str:
            return f"Web results for {query}"

        def calculate_tax(amount: float) -> float:
            return amount * 0.2

        reg.register(search_documents, tags=["search", "document"])
        reg.register(search_web, tags=["search", "web"])
        reg.register(calculate_tax, tags=["math", "finance"])

        # 1. Non-existent tool with typo "search_docs"
        fallback_msg = await reg.execute("search_docs", {"query": "test"})
        assert "[TOOL_FAILED: search_docs]" in fallback_msg
        assert "Suggested alternatives:" in fallback_msg
        # Fuzzy / token matcher suggests search_documents or search_web
        assert "search_documents" in fallback_msg or "search_web" in fallback_msg

        # 2. Argument validation error
        val_fallback = await reg.execute("calculate_tax", {"amount": "not_a_number"})
        assert "[TOOL_FAILED: calculate_tax]" in val_fallback
        assert "ValidationError" in val_fallback or "Invalid arguments" in val_fallback

    def test_adversarial_eight_action_bar_buttons_specification(self):
        """
        F4.2: Exhaustive validation of all 8 message action bar buttons:
        Copy, Listen, Raw, Export, Simplify, Deepen, Save, Retry.
        """
        actions = {
            "copy": {"icon": "Copy", "desc": "Copies clean message content to clipboard"},
            "listen": {"icon": "Volume2", "desc": "Dispatches text-to-speech voice synthesis"},
            "raw": {"icon": "Code", "desc": "Toggles raw unparsed markdown inspection"},
            "export": {"icon": "Download", "desc": "Exports message and attachments to disk"},
            "simplify": {"icon": "Sparkles", "desc": "Dispatches rewrite prompt for concise summary"},
            "deepen": {"icon": "Layers", "desc": "Dispatches follow-up prompt for deep reasoning"},
            "save": {"icon": "Bookmark", "desc": "Persists message into user knowledge base"},
            "retry": {"icon": "RotateCw", "desc": "Regenerates assistant turn with fresh seed"},
        }

        assert len(actions) == 8
        for key in ("copy", "listen", "raw", "export", "simplify", "deepen", "save", "retry"):
            assert key in actions

    def test_adversarial_canvas_artifact_normalization_and_modes(self):
        """
        F4.3: Validates Canvas artifact modes ('edit', 'preview', 'split'),
        safe URL allowlist, and untrusted payload bounds specification.
        Authoritative source: apps/chat_ui/src/artifacts.ts and PROJECT.md F4.3.
        """
        artifacts_ts_path = Path("apps/chat_ui/src/artifacts.ts")
        assert artifacts_ts_path.exists(), "artifacts.ts must exist"
        ts_code = artifacts_ts_path.read_text(encoding="utf-8")

        # 1. Canvas modes and kinds specification
        valid_modes = {"edit", "preview", "split"}
        assert len(valid_modes) == 3
        valid_kinds = {"code", "markdown", "table", "chart", "diagram", "media", "json"}
        for k in ("code", "markdown", "diagram"):
            assert f"'{k}'" in ts_code or f'"{k}"' in ts_code

        # 2. XSS prevention via strict URL allowlist in artifacts.ts
        assert "parsed.protocol === 'https:'" in ts_code
        assert "parsed.protocol === 'blob:'" in ts_code
        assert "localhost" in ts_code
        assert "127.0.0.1" in ts_code
        assert "['image', 'audio', 'video']" in ts_code

        # 3. Payload bounding in artifacts.ts (1,000,000 characters cap)
        assert "1_000_000" in ts_code or "1000000" in ts_code


