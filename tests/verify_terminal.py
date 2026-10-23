"""
Makima v2 — Phase 2 Step 8: Sandboxed Terminal & ConPTY Runner Verification Suite.

Tests:
  1. Safe command execution (echo, dir, exit code propagation, stderr capture).
  2. Destructive command interception via Guardrails (rm -rf /, format C:, drop table, etc.).
  3. Strict directory clamping within workspace and traversal escape prevention.
  4. Process timeout handling, process tree termination, and CommandTimeoutError.
  5. Safe output truncation at 100KB limit and Shannon entropy / regex secret redaction.
  6. Windows ConPTY interactive pseudo-terminal instantiation, read/write, resize, and session manager.
  7. ToolRegistry schema synthesis and end-to-end execution.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from makima.core.guardrails import DangerousCommandError
from makima.tools.registry import get_registry
from makima.tools.terminal import (
    CommandTimeoutError,
    ConPTYSession,
    clamp_to_workspace,
    execute_command,
    get_conpty_manager,
)
from makima.tools.terminal.conpty import PYWINPTY_AVAILABLE


# ---------------------------------------------------------------------------
# Test 1: Safe Command Execution
# ---------------------------------------------------------------------------

async def test_safe_command_execution():
    print("\n[TEST 1] Testing safe command execution (echo, dir, exit code, stderr)...")

    # 1. Echo test
    echo_res = await execute_command("echo Hello Makima Terminal")
    assert echo_res["exit_code"] == 0, f"Expected exit_code 0, got {echo_res['exit_code']}"
    assert "Hello Makima Terminal" in echo_res["stdout"], f"Missing echo output in stdout: {echo_res['stdout']}"
    assert echo_res["timed_out"] is False
    assert echo_res["truncated"] is False
    print("  [PASS] 'echo Hello Makima Terminal' executed successfully.")

    # 2. Directory listing test
    dir_res = await execute_command("dir")
    assert dir_res["exit_code"] == 0, f"Expected exit_code 0, got {dir_res['exit_code']}"
    assert len(dir_res["stdout"]) > 0, "Directory listing stdout was empty."
    print("  [PASS] 'dir' executed successfully.")

    # 3. Non-zero exit code propagation
    code_res = await execute_command('python -c "import sys; sys.exit(42)"')
    assert code_res["exit_code"] == 42, f"Expected exit_code 42, got {code_res['exit_code']}"
    print("  [PASS] Exit code 42 correctly captured.")





    # 4. Stderr stream capture
    err_res = await execute_command('python -c "import sys; sys.stderr.write(\'fatal_custom_error\'); sys.exit(1)"')
    assert err_res["exit_code"] == 1, f"Expected exit_code 1, got {err_res['exit_code']}"
    assert "fatal_custom_error" in err_res["stderr"], f"Expected stderr to contain error text, got: {err_res['stderr']}"
    print("  [PASS] Stderr output captured successfully.")


# ---------------------------------------------------------------------------
# Test 2: Dangerous Command Interception
# ---------------------------------------------------------------------------

async def test_dangerous_command_interception():
    print("\n[TEST 2] Testing dangerous command interception via Guardrails...")

    dangerous_commands = [
        ("rm -rf /", "Recursive root deletion"),
        ("rm -rf ..", "Recursive parent traversal deletion"),
        ("format C: /fs:NTFS", "Drive format attempt"),
        ("DROP TABLE users;", "Destructive SQL DROP"),
        ("TRUNCATE TABLE accounts;", "Destructive SQL TRUNCATE"),
        ("diskpart", "Diskpart manipulation"),
        ("shutdown /s /t 0", "Host shutdown"),
    ]

    for cmd, label in dangerous_commands:
        intercepted = False
        try:
            await execute_command(cmd)
        except DangerousCommandError as exc:
            intercepted = True
            print(f"  [PASS] Intercepted '{cmd}' ({label}): {exc}")

        assert intercepted, f"Security failure! Destructive command '{cmd}' ({label}) was NOT intercepted!"


# ---------------------------------------------------------------------------
# Test 3: Directory Clamping within Workspace
# ---------------------------------------------------------------------------

async def test_directory_clamping():
    print("\n[TEST 3] Testing directory clamping and traversal escape prevention...")

    with tempfile.TemporaryDirectory() as temp_dir:
        ws = Path(temp_dir).resolve()
        sub_dir = ws / "allowed_sub"
        sub_dir.mkdir(parents=True, exist_ok=True)

        # 1. cwd=None clamps to workspace
        c_none = clamp_to_workspace(None, workspace_dir=ws)
        assert c_none == ws, f"Expected workspace {ws}, got {c_none}"
        print("  [PASS] cwd=None resolved to workspace root.")

        # 2. Subdirectory inside workspace is permitted
        c_sub = clamp_to_workspace("allowed_sub", workspace_dir=ws)
        assert c_sub == sub_dir, f"Expected sub_dir {sub_dir}, got {c_sub}"
        print("  [PASS] Legitimate subdirectory inside workspace resolved properly.")

        # 3. Traversal escape attempt clamped back to workspace root
        c_escape = clamp_to_workspace("../../system32", workspace_dir=ws)
        assert c_escape == ws, f"Traversal escape was not clamped to workspace root: {c_escape}"
        print("  [PASS] Traversal escape '../../system32' safely clamped to workspace root.")

        # 4. Absolute path outside workspace clamped back to workspace root
        c_win = clamp_to_workspace("C:\\Windows", workspace_dir=ws)
        assert c_win == ws, f"Absolute escape was not clamped to workspace root: {c_win}"
        print("  [PASS] Absolute outside path 'C:\\Windows' safely clamped to workspace root.")

        # 5. Live command execution respects directory clamping
        exec_res = await execute_command("cd", cwd="../../escape_attempt", workspace_dir=str(ws))
        assert exec_res["cwd"] == str(ws), f"Command did not execute in clamped cwd: {exec_res['cwd']}"
        print("  [PASS] Live command execution ran within clamped workspace root.")


# ---------------------------------------------------------------------------
# Test 4: Timeout Handling and Process Tree Termination
# ---------------------------------------------------------------------------

async def test_timeout_handling():
    print("\n[TEST 4] Testing strict execution timeout handling...")

    # 1. Non-raising timeout handling (default for LLM agent loops)
    res_timeout = await execute_command("ping 127.0.0.1 -n 10", timeout_seconds=1)
    assert res_timeout["timed_out"] is True, "Command should have flagged timed_out=True"
    assert res_timeout["exit_code"] == 124, f"Expected timeout exit_code 124, got {res_timeout['exit_code']}"
    assert "timed out after 1" in res_timeout["stderr"], f"Expected timeout message in stderr: {res_timeout['stderr']}"
    print("  [PASS] Command timeout handled gracefully (timed_out=True, exit_code=124).")

    # 2. Raising timeout handling with CommandTimeoutError
    raised_timeout = False
    try:
        await execute_command("ping 127.0.0.1 -n 10", timeout_seconds=1, raise_on_timeout=True)
    except CommandTimeoutError as exc:
        raised_timeout = True
        assert isinstance(exc, TimeoutError)
        assert exc.timeout_seconds == 1.0
        print(f"  [PASS] CommandTimeoutError correctly raised when requested: {exc}")

    assert raised_timeout, "Expected CommandTimeoutError was not raised!"


# ---------------------------------------------------------------------------
# Test 5: Safe Output Truncation & Secret Redaction
# ---------------------------------------------------------------------------

async def test_output_truncation_and_secret_redaction():
    print("\n[TEST 5] Testing safe output truncation (max 100KB) and secret redaction...")

    # 1. Truncation test with > 120KB generated output
    cmd_large = 'python -c "print(\'A\' * 130000)"'
    large_res = await execute_command(cmd_large)
    assert large_res["truncated"] is True, "Output was not flagged as truncated!"
    assert "[Output truncated: exceeded 100KB limit]" in large_res["stdout"]
    # Byte length should be clamped to ~100KB + notice message length
    assert len(large_res["stdout"].encode("utf-8")) <= (100 * 1024 + 200)
    print("  [PASS] Output cleanly truncated at 100KB limit.")

    # 2. Secret token redaction test
    cmd_secret = 'python -c "print(\'API_TOKEN=sk-abcdef1234567890abcdef1234567890\')"'
    sec_res = await execute_command(cmd_secret)
    assert "[REDACTED_SECRET]" in sec_res["stdout"], "Secret was not redacted with [REDACTED_SECRET]"
    assert "sk-abcdef1234567890" not in sec_res["stdout"], "Raw secret leaked in stdout!"
    print("  [PASS] Known provider API key signature successfully redacted.")


# ---------------------------------------------------------------------------
# Test 6: Windows ConPTY Wrapper & Session Lifecycle
# ---------------------------------------------------------------------------

def test_conpty_session_and_manager():
    print("\n[TEST 6] Testing Windows ConPTY wrapper and interactive session manager...")

    assert PYWINPTY_AVAILABLE, "pywinpty must be installed and available for ConPTY runner."

    # 1. ConPTY direct session lifecycle
    session = ConPTYSession(command="cmd.exe", dimensions=(24, 80))
    try:
        assert session.is_alive is True, "ConPTY session should be active."
        assert session.pid is not None and session.pid > 0, f"Invalid PID: {session.pid}"
        print(f"  [PASS] ConPTY session spawned successfully (PID: {session.pid}).")

        # Drain any initial console banner
        session.read_all(timeout=0.2)

        # Write command to PTY
        session.write("echo CONPTY_INTERACTIVE_VERIFIED\r\n")

        # Read until token appears
        read_output = session.read_until("CONPTY_INTERACTIVE_VERIFIED", timeout=4.0)
        assert "CONPTY_INTERACTIVE_VERIFIED" in read_output, f"Target token not found in output: {repr(read_output)}"
        print("  [PASS] PTY write and read_until verified.")

        # Test window resize
        session.resize(cols=100, rows=30)
        assert session.dimensions == (30, 100), f"Expected (30, 100), got {session.dimensions}"
        print("  [PASS] PTY window resized to (30, 100).")

    finally:
        session.close()
        assert session.is_alive is False, "Session should be terminated after close()."
        print("  [PASS] ConPTY session closed cleanly.")

    # 2. Context manager test
    with ConPTYSession(command="cmd.exe") as ctx_sess:
        assert ctx_sess.is_alive is True
    assert ctx_sess.is_alive is False
    print("  [PASS] ConPTY context manager protocol operational.")

    # 3. ConPTY dangerous command block
    conpty_blocked = False
    try:
        ConPTYSession(command="rm -rf /")
    except DangerousCommandError:
        conpty_blocked = True
        print("  [PASS] ConPTY intercepted destructive command 'rm -rf /'.")
    assert conpty_blocked, "ConPTY failed to intercept dangerous command!"

    # 4. ConPTY Manager test
    mgr = get_conpty_manager()
    sess_id = "test_interactive_session_1"
    mgr_sess = mgr.create_session(session_id=sess_id, command="cmd.exe")
    assert mgr.get_session(sess_id) is not None, "Session not found in ConPTYManager"
    assert mgr_sess.is_alive is True

    # List active sessions
    active_list = mgr.list_sessions()
    assert any(s["session_id"] == sess_id for s in active_list), "Created session missing from list"

    # Close via manager
    closed = mgr.close_session(sess_id)
    assert closed is True, "Failed to close session via ConPTYManager"
    assert mgr.get_session(sess_id) is None
    print("  [PASS] ConPTYManager session creation, listing, and destruction operational.")


# ---------------------------------------------------------------------------
# Test 7: ToolRegistry Integration
# ---------------------------------------------------------------------------

async def test_tool_registry_integration():
    print("\n[TEST 7] Testing ToolRegistry discovery and tool execution...")

    reg = get_registry()
    assert "execute_command" in reg, "execute_command tool is not registered in ToolRegistry!"

    tool_obj = reg["execute_command"]
    assert "terminal" in tool_obj.tags
    assert "command" in tool_obj.parameters_schema["properties"]
    assert "command" in tool_obj.parameters_schema.get("required", [])
    print("  [PASS] execute_command tool metadata and Pydantic schema verified.")

    # Execute via ToolRegistry
    reg_res = await reg.execute("execute_command", {"command": "echo Registry Tool Dispatch"})
    assert reg_res["exit_code"] == 0
    assert "Registry Tool Dispatch" in reg_res["stdout"]
    print("  [PASS] ToolRegistry.execute('execute_command') executed successfully.")


# ---------------------------------------------------------------------------
# Main Suite Runner
# ---------------------------------------------------------------------------

async def main():
    print("=" * 75, flush=True)
    print("MAKIMA v2 — STEP 8: SANDBOXED TERMINAL & ConPTY RUNNER VERIFICATION", flush=True)
    print("=" * 75, flush=True)

    print("\nStarting Test 1...", flush=True)
    await test_safe_command_execution()
    print("\nStarting Test 2...", flush=True)
    await test_dangerous_command_interception()
    print("\nStarting Test 3...", flush=True)
    await test_directory_clamping()
    print("\nStarting Test 4...", flush=True)
    await test_timeout_handling()
    print("\nStarting Test 5...", flush=True)
    await test_output_truncation_and_secret_redaction()
    print("\nStarting Test 6...", flush=True)
    test_conpty_session_and_manager()
    print("\nStarting Test 7...", flush=True)
    await test_tool_registry_integration()

    print("\n" + "=" * 75, flush=True)
    print("ALL TERMINAL & ConPTY RUNNER TESTS PASSED (EXIT CODE 0)", flush=True)
    print("=" * 75, flush=True)



if __name__ == "__main__":
    asyncio.run(main())
