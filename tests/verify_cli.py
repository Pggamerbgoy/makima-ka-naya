"""
Verification Suite for Phase 2 Step 17: Rich Terminal CLI (makima/cli/).
Tests argument parsing, tools list, status diagnostics, gateway runner, and interactive chat REPL.
Must exit with code 0 upon success.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console

from makima.cli import cli_main
from makima.cli.main import build_parser, setup_gateway_daemon
from makima.core.engine import EngineResult
from makima.provider.adapters.base import Message, ProviderResponse, ToolCall
from makima.tools.registry import Tool, ToolRegistry, get_registry


# -----------------------------------------------------------------------------
# Mock Implementations for Deterministic Testing
# -----------------------------------------------------------------------------

class MockHermesAgentEngine:
    """Mock agent engine producing deterministic responses without external LLM calls."""

    def __init__(self, response_text: str = "Mock answer from Makima Hermes engine."):
        self.response_text = response_text
        self.recorded_prompts: List[str] = []
        self.recorded_tasks: List[Optional[str]] = []
        self.call_count = 0

    async def run(
        self,
        prompt: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        tools: Optional[Any] = None,
        task: Optional[str] = None,
        on_turn_end: Optional[Any] = None,
        **kwargs: Any,
    ) -> EngineResult:
        self.call_count += 1
        if prompt:
            self.recorded_prompts.append(prompt)
        self.recorded_tasks.append(task)

        # Trigger on_turn_end with a mock tool call on turn 1 to test spinner progress
        if on_turn_end:
            dummy_resp = ProviderResponse(
                content="Checking status...",
                tool_calls=[ToolCall(id="call_mock_1", name="execute_command", arguments={"command": "echo test"})],
            )
            on_turn_end(1, dummy_resp)

        out_messages: List[Message] = []
        if messages:
            out_messages.extend(messages)
        if prompt:
            out_messages.append(Message(role="user", content=prompt))
        out_messages.append(Message(role="assistant", content=self.response_text))

        return EngineResult(
            content=self.response_text,
            messages=out_messages,
            turn_count=1,
            tool_calls_executed=1,
            completed=True,
            model_used="mock-hermes-flash",
            latency_ms=35.5,
        )


class MockGatewayDaemon:
    """Mock gateway daemon that simulates running and stopping cleanly."""

    def __init__(self):
        self.adapters = {"telegram": MagicMock(), "discord": MagicMock()}
        class MockSecurity:
            pairing_code_enabled = True
            allow_all_users = False
        self.security = MockSecurity()
        self.run_called = False

    async def run_forever(self) -> None:
        self.run_called = True


# -----------------------------------------------------------------------------
# Test Cases
# -----------------------------------------------------------------------------

def test_argument_parser() -> None:
    """Verifies that all CLI subcommands and flags are correctly configured."""
    print("--> [1/7] Testing argument parser structure...")
    parser = build_parser()

    # Help check
    assert parser.prog == "makima"

    # Chat subcommands
    args_chat = parser.parse_args(["chat", "--task", "code", "--message", "hello", "--no-markdown"])
    assert args_chat.subcommand == "chat"
    assert args_chat.task == "code"
    assert args_chat.message == "hello"
    assert args_chat.no_markdown is True

    # Tools subcommands
    args_tools = parser.parse_args(["tools", "list", "--tag", "terminal"])
    assert args_tools.subcommand == "tools"
    assert args_tools.tools_action == "list"
    assert args_tools.tag == "terminal"

    # Gateway subcommands
    args_gw = parser.parse_args(["gateway", "run", "--host", "0.0.0.0", "--port", "9000"])
    assert args_gw.subcommand == "gateway"
    assert args_gw.gateway_action == "run"
    assert args_gw.host == "0.0.0.0"
    assert args_gw.port == 9000

    # Status subcommand
    args_status = parser.parse_args(["status"])
    assert args_status.subcommand == "status"

    print("    [PASS] Argument parser verified.")


def test_empty_and_help_args() -> None:
    """Verifies that running with empty arguments returns exit code 0."""
    print("--> [2/7] Testing empty CLI arguments...")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False)

    exit_code = cli_main([], console=console)
    assert exit_code == 0
    print("    [PASS] Empty CLI arguments handled cleanly.")


def test_tools_list() -> None:
    """Verifies 'makima tools list' renders the table and supports tag filters."""
    print("--> [3/7] Testing 'makima tools list' subcommand...")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False)

    exit_code = cli_main(["tools", "list"], console=console)
    assert exit_code == 0
    output = buf.getvalue()

    # Check for expected columns and tool entries
    assert "Makima Registered Tools" in output
    assert "execute_command" in output
    assert "read_file" in output
    assert "Total registered tools" in output

    # Check tag filtering
    buf_tag = io.StringIO()
    console_tag = Console(file=buf_tag, force_terminal=False)
    exit_code_tag = cli_main(["tools", "list", "--tag", "terminal"], console=console_tag)
    assert exit_code_tag == 0
    output_tag = buf_tag.getvalue()
    assert "execute_command" in output_tag
    assert "Filter: tag='terminal'" in output_tag

    print("    [PASS] 'makima tools list' verified.")


def test_status_dashboard() -> None:
    """Verifies 'makima status' diagnostic dashboard rendering."""
    print("--> [4/7] Testing 'makima status' subcommand...")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False)

    exit_code = cli_main(["status"], console=console)
    assert exit_code == 0
    output = buf.getvalue()

    # Assert presence of key system diagnostic tables
    assert "1. Host System Resources" in output
    assert "CPU Load" in output
    assert "System RAM" in output
    assert "Disk Storage" in output
    assert "2. Model Providers & Zero-Cost Routing" in output
    assert "fast_chat" in output
    assert "3. Dual-Tier Memory Engine State" in output
    assert "Tier 1: MEMORY.md" in output
    assert "Tier 1: USER.md" in output
    assert "Tier 2: Episodic SQLite" in output

    print("    [PASS] 'makima status' diagnostic dashboard verified.")


def test_chat_single_message() -> None:
    """Verifies 'makima chat -m <message>' non-interactive mode."""
    print("--> [5/7] Testing 'makima chat -m' single message mode...")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False)
    mock_engine = MockHermesAgentEngine("Test single prompt response.")

    exit_code = cli_main(
        ["chat", "-m", "What is the status of the engine?", "--task", "fast_chat"],
        console=console,
        engine=mock_engine,
    )
    assert exit_code == 0
    assert mock_engine.call_count == 1
    assert "What is the status of the engine?" in mock_engine.recorded_prompts
    output = buf.getvalue()
    assert "Test single prompt response." in output
    assert "mock-hermes-flash" in output

    print("    [PASS] Single message execution verified.")


def test_chat_interactive_repl() -> None:
    """Verifies full interactive REPL session with escape commands and simulated chat turn."""
    print("--> [6/7] Testing 'makima chat' interactive REPL loop...")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False)
    mock_engine = MockHermesAgentEngine("Interactive turn response.")

    # Scripted sequence of user actions in the REPL
    simulated_inputs = [
        ":help",                               # Should display REPL commands
        ":tools",                              # Should display registered tools
        ":status",                             # Should display diagnostics
        ":reset",                              # Should clear conversation history
        "How do I automate browser actions?",  # Should query agent engine
        ":quit",                               # Should terminate REPL cleanly
    ]

    def mock_prompt_fn(prompt_str: str) -> str:
        assert simulated_inputs, "Unexpected prompt request with empty simulated inputs."
        return simulated_inputs.pop(0)

    exit_code = cli_main(
        ["chat"],
        console=console,
        engine=mock_engine,
        prompt_fn=mock_prompt_fn,
    )

    assert exit_code == 0
    assert len(simulated_inputs) == 0, f"Unconsumed inputs remaining: {simulated_inputs}"
    assert mock_engine.call_count == 1
    assert "How do I automate browser actions?" in mock_engine.recorded_prompts

    output = buf.getvalue()
    # Check that interactive elements were displayed
    assert "Interactive Chat REPL" in output
    assert "Makima REPL Commands" in output
    assert "Makima Registered Tools" in output
    assert "1. Host System Resources" in output
    assert "Conversation history reset." in output
    assert "Interactive turn response." in output
    assert "Goodbye!" in output

    print("    [PASS] Interactive REPL cycle verified.")


def test_gateway_run() -> None:
    """Verifies 'makima gateway run' with a mock supervisor daemon."""
    print("--> [7/7] Testing 'makima gateway run' subcommand...")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False)
    mock_daemon = MockGatewayDaemon()

    exit_code = cli_main(
        ["gateway", "run"],
        console=console,
        daemon=mock_daemon,
    )
    assert exit_code == 0
    assert mock_daemon.run_called is True
    output = buf.getvalue()
    assert "Starting Makima Gateway Daemon" in output
    assert "telegram, discord" in output

    print("    [PASS] 'makima gateway run' verified.")


# -----------------------------------------------------------------------------
# Main Test Runner
# -----------------------------------------------------------------------------

def main() -> int:
    print("======================================================================")
    print("Makima v2 Phase 2 Step 17 — Rich Terminal CLI Verification Suite")
    print("======================================================================\n")

    try:
        test_argument_parser()
        test_empty_and_help_args()
        test_tools_list()
        test_status_dashboard()
        test_chat_single_message()
        test_chat_interactive_repl()
        test_gateway_run()

        print("\n======================================================================")
        print(">>> ALL 7 CLI VERIFICATION TESTS PASSED SUCCESSFULLY! (Exit Code: 0) <<<")
        print("======================================================================")
        return 0

    except AssertionError as ae:
        print(f"\n[FAIL] Assertion failed: {ae}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as exc:
        print(f"\n[FAIL] Unexpected error: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
