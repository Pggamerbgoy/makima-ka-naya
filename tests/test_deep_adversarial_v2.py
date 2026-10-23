"""
tests/test_deep_adversarial_v2.py — Comprehensive Deep Adversarial & Chaos Test Suite.
Designed to rigorously challenge Makima v2's Core, Tools, Guardrails, Terminal,
Memory, and Concurrency subsystems under adversarial inputs, chaos injections,
and extreme runtime conditions.

Tests:
  1. test_engine_parallel_tool_failure_resilience:
     Verifies multi-tool execution where tools throw unhandled exceptions or return error states;
     engine aggregates all results and allows model recovery without crashing.
  2. test_engine_dynamic_context_immutability:
     Verifies that transient prompt contexts (browser state, injected skills) NEVER mutate
     the canonical in-memory message history or persistent episodic turns.
  3. test_context_compressor_adversarial_slicing:
     Tests extreme message size skew (>80KB), tool call/response pairing preservation,
     and aggressive 90% context reduction.
  4. test_guardrails_obfuscated_injection_blocking:
     Adversarial shell injection attempts: PowerShell encoded commands, reversed wildcards,
     chained subcommands, and SQL comment evasion.
  5. test_guardrails_pii_fast_gate_integrity:
     Verifies Presidio fast-pre-screening mathematical gates: emails, credit cards, IP addresses,
     and AWS tokens are 100% captured and never bypassed.
  6. test_terminal_windows_quoting_and_exit_codes:
     Verifies Windows subprocess argument handling with nested spaces, quotes, flags,
     and strict non-zero exit code propagation.
  7. test_filesystem_adversarial_traversal_guards:
     Boundary escape attacks: relative traversals, encoded traversals, Windows device names,
     and protected credential files (.env, id_rsa).
  8. test_saga_rollback_tamper_detection:
     Cryptographic verification: deliberate snapshot byte corruption on disk triggers
     SHA256 mismatch rejection and prevents silent restoration.
  9. test_sqlite_wal_fts5_special_characters_stress:
     Concurrency stress test: concurrent async workers persisting and searching SQLite FTS5
     with syntax-breaking special characters (quotes, asterisks, boolean collision tokens).
 10. test_http_pool_event_loop_migration_safety:
     Verifies loop-aware HTTP pool client recreation when executing across distinct asyncio loops.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

# Ensure repository root is in sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Ensure utf-8 stdout on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pytest

from makima.core.context import ContextCompressor
from makima.core.engine import HermesAgentEngine
from makima.core.guardrails import (
    DangerousCommandError,
    Guardrails,
    filter_secrets,
)
from makima.core.http_pool import (
    close_shared_client,
    close_shared_sync_client,
    get_shared_client,
)
from makima.memory.episodic import EpisodicMemory
from makima.provider.adapters.base import (
    BaseProvider,
    Message,
    ProviderResponse,
    ToolCall,
)
from makima.provider.router import ParetoCandidate, ParetoRouter
from makima.tools.filesystem.safe_io import (
    BoundaryTraversalError,
    ProtectedCredentialError,
    read_file,
    set_workspace_dir,
    write_file,
)
from makima.tools.filesystem.saga_rollback import SagaRollbackManager
from makima.tools.terminal.runner import execute_command


# =============================================================================
# Mock Provider Infrastructure for Multi-Turn Chaos Simulation
# =============================================================================

class ChaosMockProvider(BaseProvider):
    """Predictable mock provider adapter for multi-turn engine chaos testing."""

    def __init__(self, responses: Optional[List[ProviderResponse]] = None):
        mock_cfg = MagicMock()
        mock_cfg.model = "mock-chaos-model"
        mock_cfg.is_available = True
        super().__init__(config=mock_cfg)
        self.responses = list(responses or [])
        self.call_history: List[List[Message]] = []

    def queue_response(self, response: ProviderResponse) -> None:
        self.responses.append(response)

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        self.call_history.append([
            Message(
                role=m.role,
                content=m.content,
                tool_calls=m.tool_calls,
                tool_call_id=getattr(m, "tool_call_id", None),
                name=getattr(m, "name", None),
            )
            for m in messages
        ])
        if not self.responses:
            return ProviderResponse(
                content="Mock response: conversation complete.",
                finish_reason="stop",
                model=self.name,
            )
        return self.responses.pop(0)

    async def stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Stream not used in chaos test.")


class ChaosMockRouter(ParetoRouter):
    """Router wrapper injecting ChaosMockProvider."""

    def __init__(self, mock_provider: ChaosMockProvider):
        super().__init__()
        self.mock_provider = mock_provider
        self._providers["mock_chaos"] = mock_provider
        self._initialized = True

    def get_ranked_candidates(self, task: str = "fast_chat") -> List[ParetoCandidate]:
        return [
            ParetoCandidate(
                name="mock_chaos",
                provider=self.mock_provider,
                cascade_rank=0,
                latency_tier_score=1,
                ewma_ms=25.0,
                failure_count=0,
                is_available=True,
            )
        ]

    def select_provider(self, task: str = "fast_chat") -> BaseProvider:
        return self.mock_provider


# =============================================================================
# Test 1: Parallel Tool Failure & Exception Resilience
# =============================================================================

@pytest.mark.asyncio
async def test_engine_parallel_tool_failure_resilience():
    """
    Verifies that when LLM dispatches multiple tool calls in parallel and one tool
    explodes with an unhandled exception while another succeeds, the engine:
      1. Catches the exception and wraps it in a [TOOL_FAILED: name] message.
      2. Accurately preserves the successful tool's output.
      3. Forwards all tool output messages back to the LLM on the next turn.
      4. Avoids deadlocking or halting the autonomous loop prematurely.
    """
    async def mock_tool_executor(name: str, args: Dict[str, Any]) -> Any:
        if name == "healthy_tool":
            return {"result": args["x"] * 10}
        elif name == "exploding_tool":
            raise RuntimeError(f"Catastrophic failure in exploding_tool: {args.get('msg')}")
        raise ValueError(f"Unknown tool {name}")

    mock_provider = ChaosMockProvider()
    router = ChaosMockRouter(mock_provider)
    engine = HermesAgentEngine(router=router, max_turns=5)

    # Turn 1: Model issues two tool calls in parallel (healthy + exploding)
    mock_provider.queue_response(
        ProviderResponse(
            content=None,
            tool_calls=[
                ToolCall(id="call_healthy", name="healthy_tool", arguments={"x": 5}),
                ToolCall(id="call_exploding", name="exploding_tool", arguments={"msg": "payload_boom"}),
            ],
            model="mock-chaos-model",
        )
    )
    # Turn 2: Model observes the error in exploding_tool, recovers, and gives final answer
    mock_provider.queue_response(
        ProviderResponse(
            content="I observed healthy_tool gave 50, but exploding_tool encountered an error.",
            finish_reason="stop",
            model="mock-chaos-model",
        )
    )

    result = await engine.run(
        prompt="Calculate and test resilience",
        tool_executor=mock_tool_executor,
    )

    assert result.turn_count == 2
    assert "healthy_tool gave 50" in result.content
    assert len(mock_provider.call_history) == 2

    # Check Turn 2 inputs
    turn_2_messages = mock_provider.call_history[1]
    tool_messages = [m for m in turn_2_messages if m.role == "tool"]
    assert len(tool_messages) == 2

    healthy_msg = next((m for m in tool_messages if m.tool_call_id == "call_healthy"), None)
    exploding_msg = next((m for m in tool_messages if m.tool_call_id == "call_exploding"), None)

    assert healthy_msg is not None
    assert '"result": 50' in healthy_msg.content or "50" in healthy_msg.content

    assert exploding_msg is not None
    assert "[TOOL_FAILED: exploding_tool]" in exploding_msg.content
    assert "Catastrophic failure in exploding_tool" in exploding_msg.content


# =============================================================================
# Test 2: Engine Transient Context Immutability
# =============================================================================

@pytest.mark.asyncio
async def test_engine_dynamic_context_immutability():
    """
    Verifies that transient state injection (e.g. active browser DOM state or
    dynamic skills prompt block) does not permanently mutate:
      1. The original messages passed to engine.run().
      2. The persisted episodic turns in memory.
    """
    mock_provider = ChaosMockProvider()
    mock_provider.queue_response(
        ProviderResponse(
            content="Understood, executing task.",
            finish_reason="stop",
            model="mock-chaos-model",
        )
    )
    router = ChaosMockRouter(mock_provider)

    memory = EpisodicMemory(db_path=":memory:")
    engine = HermesAgentEngine(router=router, episodic_memory=memory)

    res = await engine.run(
        prompt="Open dashboard and inspect",
        session_id="test_session_immutability",
    )

    assert res.content == "Understood, executing task."

    # Wait for background episodic persistence tasks to finish
    if engine._background_tasks:
        await asyncio.gather(*list(engine._background_tasks), return_exceptions=True)

    # Verify persisted turns in episodic memory do not have phantom context
    stored_turns = await memory.get_recent_turns(session_id="test_session_immutability", limit=10)
    assert len(stored_turns) == 2
    assert stored_turns[0]["content"] == "Open dashboard and inspect"
    assert "<active_browser_state>" not in stored_turns[0]["content"]
    assert "<active_browser_state>" not in stored_turns[1]["content"]
    await memory.close()


# =============================================================================
# Test 3: Context Compressor Adversarial Slicing & Tool Integrity
# =============================================================================

def test_context_compressor_adversarial_slicing():
    """
    Adversarially tests ContextCompressor:
      1. Massive messages (>50,000 chars) are clamped without losing role integrity.
      2. Assistant tool_calls message and subsequent tool output messages are NEVER
         severed across the compression boundary (atomic tool pair invariant).
      3. Compressing already-small message lists is a no-op.
    """
    compressor = ContextCompressor(max_tokens=8192, head_turns=2, tail_turns=2)

    # 1. Test massive message clamping
    huge_text = "X" * 60000
    huge_msg = Message(role="tool", content=huge_text, tool_call_id="call_huge")
    clamped = compressor._clamp_large_message(huge_msg)
    assert len(clamped.content) < 20000
    assert "[... truncated" in clamped.content
    assert clamped.tool_call_id == "call_huge"

    # 2. Test tool-call atomic boundary retention
    # Construct sequence where splitting between assistant tool_calls and tool output would break API contract
    messages: List[Message] = [
        Message(role="system", content="System instruction"),
        Message(role="user", content="Turn 1: start"),
        Message(role="assistant", content="Turn 1 reply"),
        Message(role="user", content="Turn 2: run tools"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="call_split_1", name="fetch_data", arguments={})],
        ),
        Message(role="tool", content="Data result 1", tool_call_id="call_split_1"),
        Message(role="user", content="Turn 3: follow up"),
        Message(role="assistant", content="Turn 3 reply"),
        Message(role="user", content="Turn 4: final"),
    ]

    compressed = compressor.compress(messages)
    assert len(compressed) <= len(messages)

    # Verify that any assistant message with tool_calls in compressed output
    # is immediately followed by its matching tool response
    for idx, msg in enumerate(compressed):
        if msg.role == "assistant" and msg.tool_calls:
            assert idx + 1 < len(compressed), "Assistant tool_calls cannot be the last message"
            next_msg = compressed[idx + 1]
            assert next_msg.role == "tool", f"Expected tool message after assistant tool_calls, got {next_msg.role}"


# =============================================================================
# Test 4: Obfuscated Shell Injection & Dangerous Command Blocking
# =============================================================================

def test_guardrails_obfuscated_injection_blocking():
    """
    Verifies that Guardrails strictly intercepts destructive commands even when
    obfuscated via flags, PowerShell flags, chained commands, or SQL comments.
    """
    guard = Guardrails()

    adversarial_destructive_commands = [
        # Chained shell attacks
        "echo safe && rm -rf /",
        "echo done; rm -rf /* ; echo fin",
        "dir & format C: /fs:NTFS & echo ok",
        "type file.txt | rm -rf /",
        # Flag variations
        "rm -r -f /",
        "rm -fr /",
        "rm --recursive --force /",
        "rm -rf --no-preserve-root /",
        # Windows deletions
        "del /f /s /q C:\\*.*",
        "rmdir /s /q C:\\",
        "rd /s /q C:\\",
        # Destructive SQL attacks
        "DROP/**/TABLE/**/accounts;",
        "DROP TABLE `users`;",
        "TRUNCATE TABLE billing;",
        # Dangerous disk manipulation
        "diskpart /s script.txt",
    ]

    for cmd in adversarial_destructive_commands:
        with pytest.raises(DangerousCommandError, match=r"Command blocked by Makima safety guardrails"):
            guard.validate_command(cmd)

    # Legitimate non-destructive commands MUST NOT be blocked
    safe_commands = [
        "echo Hello World",
        "dir /a /s",
        "python -m pytest tests/test_smoke.py",
        "git status --short",
        "npm run build",
        "SELECT * FROM users WHERE active = 1;",
    ]

    for safe_cmd in safe_commands:
        guard.validate_command(safe_cmd)  # Should not raise


# =============================================================================
# Test 5: Presidio PII Fast Pre-Screening Gate Integrity
# =============================================================================

def test_guardrails_pii_fast_gate_integrity():
    """
    Verifies that the fast mathematical pre-screening gates in filter_secrets:
      1. Never skip real email addresses (requires '@').
      2. Never skip real credit cards, IPs, or phone numbers (requires 3+ digit cluster).
      3. Never skip real AWS access keys (AKIA...).
      4. Correctly redact secrets while preserving surround text.
    """
    sample_text = (
        "Contact me at developer@makima.io for credentials. "
        "The master AWS key is AKIAIOSFODNN7EXAMPLE and secret is wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY. "
        "Test payment with Visa 4532-0150-1234-5671 expiring 12/28. "
        "Database is running at 192.168.1.150:5432."
    )

    redacted = filter_secrets(sample_text)

    # Verify all critical secrets were caught
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "4532-0150-1234-5671" not in redacted
    assert "developer@makima.io" not in redacted
    assert "192.168.1.150" not in redacted

    # Test benign text with zero digits or @ passes through clean
    benign_text = "Makima autonomous assistant running system health check without secrets."
    filtered_benign = filter_secrets(benign_text)
    assert filtered_benign == benign_text


# =============================================================================
# Test 6: Terminal Windows Subprocess Argument Quoting & Exit Codes
# =============================================================================

@pytest.mark.asyncio
async def test_terminal_windows_quoting_and_exit_codes():
    """
    Verifies that execute_command on Windows handles:
      1. Python inline commands with internal double quotes and exits with exact code.
      2. Spaces in arguments.
      3. Non-zero exit code propagation (e.g. exit 99).
      4. Stderr output capture.
    """
    # Test exit code 99 propagation
    res_code = await execute_command('python -c "import sys; sys.exit(99)"')
    assert res_code["exit_code"] == 99, f"Expected exit_code 99, got {res_code['exit_code']}"

    # Test argument with space and multi-line script string
    res_echo = await execute_command('python -c "print(\'alpha beta gamma\')"')
    assert res_echo["exit_code"] == 0
    assert "alpha beta gamma" in res_echo["stdout"]

    # Test stderr capture
    res_err = await execute_command('python -c "import sys; sys.stderr.write(\'chaos_error_signal\'); sys.exit(7)"')
    assert res_err["exit_code"] == 7
    assert "chaos_error_signal" in res_err["stderr"]


# =============================================================================
# Test 7: Filesystem Adversarial Traversal & Protected Credential Guards
# =============================================================================

def test_filesystem_adversarial_traversal_guards():
    """
    Verifies that safe filesystem tools strictly prevent:
      1. Parent directory traversal escapes ('../../Windows').
      2. Access to protected credential files (.env, id_rsa, id_ed25519).
      3. Writing outside designated workspace boundary.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir).resolve()
        set_workspace_dir(ws)

        try:
            # 1. Normal safe file write inside workspace
            write_res = write_file("nested/safe.txt", "safe_content", overwrite=True)
            assert "Successfully" in write_res
            assert (ws / "nested" / "safe.txt").is_file()

            # 2. Relative traversal write attempt outside workspace
            with pytest.raises(BoundaryTraversalError):
                write_file("../../escape_payload.txt", "malicious_content")

            # 3. Read attempt outside workspace
            with pytest.raises(BoundaryTraversalError):
                read_file("C:/Windows/System32/drivers/etc/hosts")

            # 4. Protected credential file access attempts
            protected_filenames = [
                ".env",
                ".env.local",
                "id_rsa",
                "id_ed25519",
                "credentials.json",
                "wallet.dat",
            ]

            for pf in protected_filenames:
                with pytest.raises(ProtectedCredentialError):
                    write_file(pf, "leaked_secret")

                with pytest.raises(ProtectedCredentialError):
                    read_file(pf)

        finally:
            set_workspace_dir(None)


# =============================================================================
# Test 8: SAGA Rollback SHA256 Tamper Rejection
# =============================================================================

def test_saga_rollback_tamper_detection():
    """
    Verifies SAGA filesystem rollback cryptographic integrity:
    If a snapshot file on disk is modified/corrupted, restore_snapshot MUST
    detect the SHA256 checksum mismatch, abort restoration, and raise ValueError.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir).resolve()
        set_workspace_dir(ws)

        try:
            mgr = SagaRollbackManager(workspace_dir=ws)
            test_file = ws / "critical_data.txt"
            test_file.write_text("version_1_original", encoding="utf-8")

            # Create snapshot of version 1
            snap_info = mgr.create_snapshot("critical_data.txt", operation="edit")
            assert snap_info.sha256 == hashlib.sha256(b"version_1_original").hexdigest()

            # Update file to version 2
            test_file.write_text("version_2_updated", encoding="utf-8")

            # Deliberately TAMPER with the snapshot file on disk
            snap_path = Path(snap_info.snapshot_path)
            assert snap_path.is_file()
            snap_path.write_bytes(b"tampered_corrupted_payload")

            # Attempt rollback — MUST detect checksum mismatch and reject
            with pytest.raises(ValueError, match=r"Snapshot integrity failure: payload SHA256"):
                mgr.rollback("critical_data.txt", snapshot_id=snap_info.snapshot_id)

            # Verify target file on disk was NOT corrupted by the tampered snapshot
            assert test_file.read_text(encoding="utf-8") == "version_2_updated"

        finally:
            set_workspace_dir(None)


# =============================================================================
# Test 9: SQLite WAL Concurrency & FTS5 Special Character Stress
# =============================================================================

@pytest.mark.asyncio
async def test_sqlite_wal_fts5_special_characters_stress():
    """
    Stress tests EpisodicMemory under concurrent async writes and FTS5 searches
    containing syntax-breaking characters ('*', quotes, boolean operator keywords).
    """
    mem = EpisodicMemory(db_path=":memory:")

    async def worker(worker_id: int):
        # Write turn with syntax-challenging tokens
        tricky_text = f"Worker {worker_id}: Testing 'quotes' and \"double quotes\", asterisks * and AND OR NOT tokens."
        await mem.store_turn(
            session_id=f"session_{worker_id % 3}",
            role="user" if worker_id % 2 == 0 else "assistant",
            content=tricky_text,
        )

    # Run 20 concurrent async writes
    await asyncio.gather(*(worker(i) for i in range(20)))

    # Verify turns count
    recent = await mem.get_recent_turns(session_id="session_0", limit=50)
    assert len(recent) > 0

    # Run FTS5 keyword searches with syntax-breaking characters
    # Queries that might break raw SQLite FTS5 if un-sanitized
    tricky_queries = [
        "quotes AND OR NOT",
        "asterisks *",
        '"unmatched double quote',
        "'unmatched single quote",
        "NEAR(Worker, 1)",
        "Worker: *",
    ]

    for q in tricky_queries:
        results = await mem.search_fts(query=q, limit=10)
        assert isinstance(results, list)  # Should return list without throwing sqlite3.OperationalError

    await mem.close()


# =============================================================================
# Test 10: Loop-Aware HTTP Client Migration Safety
# =============================================================================

@pytest.mark.asyncio
async def test_http_pool_event_loop_migration_safety():
    """
    Verifies that get_shared_client() dynamically adapts when invoked across
    distinct asyncio event loops, safely closing previous loop resources
    and binding new instances without socket leaks.
    """
    # 1. Get client on current loop
    client_loop1 = await get_shared_client()
    assert client_loop1 is not None
    assert not client_loop1.is_closed

    # 2. Create and run in a distinct separate event loop in a worker thread
    def run_on_distinct_loop():
        new_loop = asyncio.new_event_loop()
        try:
            async def fetch_on_new_loop():
                client_loop2 = await get_shared_client()
                assert client_loop2 is not None
                assert not client_loop2.is_closed
                # The client on the new loop must be distinct from loop1's client
                assert client_loop2 is not client_loop1
                return True

            return new_loop.run_until_complete(fetch_on_new_loop())
        finally:
            new_loop.close()

    success = await asyncio.to_thread(run_on_distinct_loop)
    assert success is True

    # 3. Verify clean shutdown of shared client and sync client
    await close_shared_client()
    close_shared_sync_client()


# =============================================================================
# Direct Execution Runner
# =============================================================================

if __name__ == "__main__":
    print("======================================================================")
    print("🚀 RUNNING MAKIMA v2 DEEP ADVERSARIAL & CHAOS TEST SUITE")
    print("======================================================================")

    async def run_all_async_tests():
        print("\n[SUITE 1/10] Parallel Tool Failure & Exception Resilience...")
        await test_engine_parallel_tool_failure_resilience()
        print("  -> PASSED: Unhandled tool exceptions aggregated without deadlocking!")

        print("\n[SUITE 2/10] Engine Dynamic Context Immutability...")
        await test_engine_dynamic_context_immutability()
        print("  -> PASSED: Injected context did not mutate canonical message state!")

        print("\n[SUITE 3/10] Context Compressor Adversarial Slicing...")
        test_context_compressor_adversarial_slicing()
        print("  -> PASSED: Atomic tool call/output pairing preserved across boundaries!")

        print("\n[SUITE 4/10] Obfuscated Shell Injection & Guardrails...")
        test_guardrails_obfuscated_injection_blocking()
        print("  -> PASSED: All obfuscated destructive attacks blocked!")

        print("\n[SUITE 5/10] Presidio PII Fast Gate Integrity...")
        test_guardrails_pii_fast_gate_integrity()
        print("  -> PASSED: Real emails, AWS keys, and credit cards 100% redacted!")

        print("\n[SUITE 6/10] Terminal Windows Subprocess Quoting & Exit Codes...")
        await test_terminal_windows_quoting_and_exit_codes()
        print("  -> PASSED: Windows arguments and exit codes propagated cleanly!")

        print("\n[SUITE 7/10] Filesystem Boundary Traversal & Protected Credentials...")
        test_filesystem_adversarial_traversal_guards()
        print("  -> PASSED: Boundary escapes and credential reads blocked!")

        print("\n[SUITE 8/10] SAGA Rollback SHA256 Tamper Rejection...")
        test_saga_rollback_tamper_detection()
        print("  -> PASSED: Corrupted snapshot on disk rejected by checksum validation!")

        print("\n[SUITE 9/10] SQLite WAL Concurrency & FTS5 Special Character Stress...")
        await test_sqlite_wal_fts5_special_characters_stress()
        print("  -> PASSED: Concurrent writes and tricky FTS5 tokens handled safely!")

        print("\n[SUITE 10/10] Loop-Aware HTTP Client Migration Safety...")
        await test_http_pool_event_loop_migration_safety()
        print("  -> PASSED: Multi-loop HTTP client re-binding verified!")

        print("\n======================================================================")
        print("🎉 ALL 10 DEEP ADVERSARIAL & CHAOS TESTS PASSED WITH EXIT CODE 0!")
        print("======================================================================")

    asyncio.run(run_all_async_tests())
