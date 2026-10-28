"""
Tests for Feature 4: Interactive Human-in-the-Loop (HITL) Permission Prompts in makima/api/ws.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi.testclient import TestClient

from makima.api.app import create_app
import makima.api.ws as ws_module
from makima.core.engine import HermesAgentEngine
from makima.provider.adapters.base import Message, ProviderResponse, ToolCall
from makima.provider.router import ParetoRouter
from makima.tools.registry import ToolRegistry


class MockHITLRouter(ParetoRouter):
    def __init__(self, tool_name: str = "execute_command", tool_args: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.tool_name = tool_name
        self.tool_args = tool_args or {"command": "echo test"}
        self.received_tool_result: Optional[str] = None

    async def execute_with_fallback(
        self,
        task: str,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        preferred_backend: Optional[str] = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        tool_msg = next((m for m in reversed(messages) if m.role == "tool"), None)
        if tool_msg:
            self.received_tool_result = tool_msg.content
            return ProviderResponse(
                content=f"Tool finished with result: {tool_msg.content}",
                model="mock-hitl-model",
                finish_reason="stop",
            )
        return ProviderResponse(
            content="Invoking requested tool...",
            model="mock-hitl-model",
            finish_reason="tool_calls",
            tool_calls=[ToolCall(name=self.tool_name, arguments=self.tool_args, id="tc_hitl_1")],
        )


def make_test_setup(tool_name: str = "execute_command", tool_args: Optional[Dict[str, Any]] = None):
    executed: List[Dict[str, Any]] = []

    def mock_tool_fn(**kwargs):
        executed.append(kwargs)
        return f"Executed {tool_name} successfully with {kwargs}"

    registry = ToolRegistry()
    registry.register(mock_tool_fn, name=tool_name, description="Test tool", tags=["terminal", "system"])
    router = MockHITLRouter(tool_name=tool_name, tool_args=tool_args)
    engine = HermesAgentEngine(router=router)
    app = create_app(engine=engine, registry=registry)
    client = TestClient(app)
    return client, executed, router


def test_destructive_tool_triggers_permission_request():
    """Test 1: Destructive tool triggers permission_request event."""
    client, executed, router = make_test_setup(
        tool_name="execute_command",
        tool_args={"command": "dir"}
    )

    with client.websocket_connect("/ws") as ws:
        ws.send_json({
            "type": "user_message",
            "task_id": "hitl-task-1",
            "content": "run directory command",
        })

        perm_event = None
        for _ in range(15):
            event = ws.receive_json()
            if event.get("type") == "permission_request":
                perm_event = event
                break

        assert perm_event is not None, "Expected permission_request event was not received"
        assert perm_event["type"] == "permission_request"
        assert perm_event["tool"] == "execute_command"
        assert perm_event["arguments"] == {"command": "dir"}
        assert perm_event["task_id"] == "hitl-task-1"
        assert perm_event["permission_id"].startswith("perm_")

        # The status event for waiting approval follows permission_request
        status_event = ws.receive_json()
        assert status_event.get("type") == "status"
        assert "Waiting for user approval to execute execute_command" in status_event.get("stage", "")

        # Allow execution so the background run completes cleanly
        ws.send_json({
            "type": "permission_response",
            "permission_id": perm_event["permission_id"],
            "allowed": True,
        })
        for _ in range(15):
            event = ws.receive_json()
            if event.get("type") == "message":
                break

    assert len(ws_module.pending_permissions) == 0


def test_permission_allowed_executes_tool():
    """Test 2: Client sends permission_response with allowed=true, tool executes."""
    client, executed, router = make_test_setup(
        tool_name="run_command",
        tool_args={"command": "pytest -v"}
    )

    with client.websocket_connect("/ws") as ws:
        ws.send_json({
            "type": "user_message",
            "task_id": "hitl-task-2",
            "content": "run pytest",
        })

        perm_event = None
        for _ in range(15):
            event = ws.receive_json()
            if event.get("type") == "permission_request":
                perm_event = event
                break

        assert perm_event is not None
        perm_id = perm_event["permission_id"]

        # Approve execution
        ws.send_json({
            "type": "permission_response",
            "permission_id": perm_id,
            "allowed": True,
        })

        events = []
        for _ in range(15):
            event = ws.receive_json()
            events.append(event)
            if event.get("type") == "message":
                break

        tool_result_event = next((e for e in events if e.get("type") == "tool_result"), None)
        assert tool_result_event is not None
        assert tool_result_event["name"] == "run_command"
        assert "Executed run_command successfully" in str(tool_result_event["result"])

        final_msg = next((e for e in events if e.get("type") == "message"), None)
        assert final_msg is not None
        assert "Executed run_command successfully" in final_msg["content"]

    # Verify tool was actually invoked in backend
    assert len(executed) == 1
    assert executed[0] == {"command": "pytest -v"}
    assert len(ws_module.pending_permissions) == 0


def test_permission_denied_returns_denial_message():
    """Test 3: Client sends permission_response with allowed=false, tool returns denial message."""
    client, executed, router = make_test_setup(
        tool_name="delete_file",
        tool_args={"path": "/important/data.db"}
    )

    with client.websocket_connect("/ws") as ws:
        ws.send_json({
            "type": "user_message",
            "task_id": "hitl-task-3",
            "content": "delete database",
        })

        perm_event = None
        for _ in range(15):
            event = ws.receive_json()
            if event.get("type") == "permission_request":
                perm_event = event
                break

        assert perm_event is not None
        perm_id = perm_event["permission_id"]

        # Deny execution (also testing fallback 'id' field in payload)
        ws.send_json({
            "type": "permission_response",
            "id": perm_id,
            "allowed": False,
        })

        events = []
        for _ in range(15):
            event = ws.receive_json()
            events.append(event)
            if event.get("type") == "message":
                break

        tool_result_event = next((e for e in events if e.get("type") == "tool_result"), None)
        assert tool_result_event is not None
        assert tool_result_event["name"] == "delete_file"
        expected_denial = "[TOOL_PERMISSION_DENIED: delete_file] Execution was denied by the user."
        assert expected_denial in str(tool_result_event["result"])

        final_msg = next((e for e in events if e.get("type") == "message"), None)
        assert final_msg is not None
        assert expected_denial in final_msg["content"]

    # Verify tool was NOT executed in backend
    assert len(executed) == 0
    assert len(ws_module.pending_permissions) == 0


def test_destructive_arguments_trigger_permission():
    """Test 4: Tool not in destructive name set but containing destructive keyword in args triggers prompt."""
    client, executed, router = make_test_setup(
        tool_name="custom_exec",
        tool_args={"script": "rm -rf /tmp/data"}
    )

    with client.websocket_connect("/ws") as ws:
        ws.send_json({
            "type": "user_message",
            "task_id": "hitl-task-4",
            "content": "clean temp files",
        })

        perm_event = None
        for _ in range(15):
            event = ws.receive_json()
            if event.get("type") == "permission_request":
                perm_event = event
                break

        assert perm_event is not None
        assert perm_event["tool"] == "custom_exec"

        # Deny it
        ws.send_json({
            "type": "permission_response",
            "permission_id": perm_event["permission_id"],
            "allowed": False,
        })

        for _ in range(15):
            event = ws.receive_json()
            if event.get("type") == "message":
                break

    assert len(executed) == 0
    assert len(ws_module.pending_permissions) == 0


def test_non_destructive_tool_runs_without_permission_prompt():
    """Test 5: Non-destructive tool executes directly without permission prompt."""
    client, executed, router = make_test_setup(
        tool_name="read_file",
        tool_args={"path": "README.md"}
    )

    with client.websocket_connect("/ws") as ws:
        ws.send_json({
            "type": "user_message",
            "task_id": "hitl-task-5",
            "content": "read readme",
        })

        events = []
        for _ in range(15):
            event = ws.receive_json()
            events.append(event)
            if event.get("type") == "message":
                break

        # Verify NO permission_request event was sent
        assert not any(e.get("type") == "permission_request" for e in events)
        tool_result_event = next((e for e in events if e.get("type") == "tool_result"), None)
        assert tool_result_event is not None
        assert "Executed read_file successfully" in str(tool_result_event["result"])

    assert len(executed) == 1
    assert len(ws_module.pending_permissions) == 0
