"""
Verification Test Suite for Step 18: FastAPI Server & Real-time WebSocket Bridge.
Tests:
  1. GET /health: Status 200, schema validation (status, version, uptime).
  2. GET /api/status: Status 200, system metrics (CPU, RAM, disk) and provider availability.
  3. GET /api/tools: Status 200, auto-discovered tool list and OpenAI-compatible tool schemas.
  4. POST /api/chat:
     - 400 Bad Request on empty prompt/messages.
     - 200 OK with autonomous agent execution, message retention, and schema response.
  5. WebSocket /ws:
     - Ping / Pong keepalive protocol.
     - Autonomous agent streaming:
       - Status 'planning'
       - Tool call event ('tool_call')
       - Tool result event ('tool_result')
       - Final message event ('message')
       - Status 'completed'
     - Error handling on invalid/empty frames.
"""

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from fastapi.testclient import TestClient

import makima
from makima.api.app import create_app
from makima.core.engine import HermesAgentEngine
from makima.provider.adapters.base import Message, ProviderResponse, ToolCall
from makima.provider.router import ParetoRouter


class MockEngineRouter(ParetoRouter):
    """Predictable mock router for fast, deterministic, zero-cost API testing."""

    def __init__(self, responses: Optional[List[ProviderResponse]] = None):
        super().__init__()
        self.queued_responses = list(responses or [])
        self.call_count = 0

    def queue_response(self, response: ProviderResponse) -> None:
        self.queued_responses.append(response)

    async def execute_with_fallback(
        self,
        task: str,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        enable_thinking: Optional[bool] = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        self.call_count += 1
        if self.queued_responses:
            return self.queued_responses.pop(0)

        # Default echo response
        last_user_content = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "Hello",
        )
        return ProviderResponse(
            content=f"Echo response to: {last_user_content}",
            model="mock-hermes-v2",
            tool_calls=[],
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        )


def build_test_engine(mock_responses: Optional[List[ProviderResponse]] = None) -> HermesAgentEngine:
    router = MockEngineRouter(responses=mock_responses)
    return HermesAgentEngine(router=router)


def test_health_endpoint():
    print("\n" + "=" * 60)
    print("[TEST 1] Testing GET /health...")
    print("=" * 60)

    app = create_app()
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200, f"Expected status 200, got {response.status_code}"
    data = response.json()

    assert data.get("status") == "ok", f"Expected status 'ok', got {data.get('status')}"
    assert data.get("version") == makima.__version__, f"Version mismatch: {data.get('version')}"
    assert "uptime" in data and isinstance(data["uptime"], (int, float)) and data["uptime"] >= 0.0
    print(f"  [PASS] /health returned: status={data['status']}, version={data['version']}, uptime={data['uptime']}s")


def test_system_status_endpoint():
    print("\n" + "=" * 60)
    print("[TEST 2] Testing GET /api/status...")
    print("=" * 60)

    engine = build_test_engine()
    app = create_app(engine=engine)
    client = TestClient(app)

    response = client.get("/api/status")
    assert response.status_code == 200, f"Expected status 200, got {response.status_code}"
    data = response.json()

    assert data.get("status") == "operational"
    assert "system" in data
    sys_metrics = data["system"]
    assert "cpu_percent" in sys_metrics
    assert "ram_percent" in sys_metrics
    assert "ram_used_gb" in sys_metrics
    assert "ram_total_gb" in sys_metrics
    assert "disk_percent" in sys_metrics
    assert "providers" in data
    print(f"  [PASS] /api/status returned telemetry:")
    print(f"         CPU: {sys_metrics['cpu_percent']}%, RAM: {sys_metrics['ram_percent']}% ({sys_metrics['ram_used_gb']}GB / {sys_metrics['ram_total_gb']}GB)")
    print(f"         Disk: {sys_metrics['disk_percent']}%, Configured Backends: {data['providers']['configured_backends']}")


def test_tools_endpoint():
    print("\n" + "=" * 60)
    print("[TEST 3] Testing GET /api/tools...")
    print("=" * 60)

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/tools")
    assert response.status_code == 200, f"Expected status 200, got {response.status_code}"
    data = response.json()

    assert "tools" in data and isinstance(data["tools"], list)
    assert "count" in data and data["count"] == len(data["tools"])
    assert data["count"] > 0, "Expected registered tools in registry"

    first_tool = data["tools"][0]
    assert "type" in first_tool and first_tool["type"] == "function"
    assert "function" in first_tool
    assert "name" in first_tool["function"]
    assert "parameters" in first_tool["function"]

    # Verify our OS tools are present
    tool_names = {t["function"]["name"] for t in data["tools"]}
    expected_os_tools = {"list_processes", "get_system_stats", "list_open_windows", "launch_app"}
    for os_tool in expected_os_tools:
        assert os_tool in tool_names, f"Expected OS tool '{os_tool}' in /api/tools"

    print(f"  [PASS] /api/tools returned {data['count']} registered tools with valid JSON schemas.")
    print(f"         Verified presence of: {', '.join(expected_os_tools)}")


def test_chat_endpoint():
    print("\n" + "=" * 60)
    print("[TEST 4] Testing POST /api/chat...")
    print("=" * 60)

    # 1. 400 Bad Request on empty prompt/messages
    app = create_app()
    client = TestClient(app)
    bad_resp = client.post("/api/chat", json={})
    assert bad_resp.status_code == 400
    print(f"  [PASS] POST /api/chat correctly rejected empty payload with HTTP 400.")

    # 2. 200 OK single-turn chat
    engine = build_test_engine([
        ProviderResponse(
            content="Hello! I am Makima, your desktop assistant.",
            model="mock-hermes-v2",
            tool_calls=[],
            finish_reason="stop",
            usage={"total_tokens": 15},
        )
    ])
    app = create_app(engine=engine)
    client = TestClient(app)

    chat_payload = {
        "prompt": "Introduce yourself.",
        "task": "fast_chat",
        "temperature": 0.5,
    }
    resp = client.post("/api/chat", json=chat_payload)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    chat_data = resp.json()

    assert chat_data["content"] == "Hello! I am Makima, your desktop assistant."
    assert chat_data["completed"] is True
    assert chat_data["turn_count"] == 1
    assert chat_data["model_used"] == "mock-hermes-v2"
    assert len(chat_data["messages"]) >= 2  # user + assistant
    print(f"  [PASS] POST /api/chat returned valid response: '{chat_data['content']}' (latency: {chat_data['latency_ms']:.1f}ms)")


def test_websocket_ping_pong():
    print("\n" + "=" * 60)
    print("[TEST 5] Testing WebSocket /ws Ping/Pong & Errors...")
    print("=" * 60)

    app = create_app()
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        # 1. Ping
        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        assert pong.get("type") == "pong"
        assert "timestamp" in pong
        print(f"  [PASS] WebSocket ping/pong verified: {pong}")

        # 2. Empty user_message error handling
        ws.send_json({"type": "user_message", "content": ""})
        err = ws.receive_json()
        assert err.get("type") == "error"
        assert "cannot be empty" in err.get("message", "")
        print(f"  [PASS] WebSocket empty user_message error handled: {err['message']}")

        # 3. Unsupported message type
        ws.send_json({"type": "unknown_action_xyz"})
        unsupported = ws.receive_json()
        assert unsupported.get("type") == "error"
        assert "Unsupported message type" in unsupported.get("message", "")
        print(f"  [PASS] WebSocket unsupported message type handled: {unsupported['message']}")


def test_websocket_agent_streaming():
    print("\n" + "=" * 60)
    print("[TEST 6] Testing WebSocket /ws Real-time Autonomous Agent Streaming...")
    print("=" * 60)

    # Queue multi-turn simulation:
    # Turn 1: model requests tool call 'get_system_stats'
    # Turn 2: model synthesizes final answer
    mock_responses = [
        ProviderResponse(
            content="",
            model="mock-hermes-v2",
            tool_calls=[
                ToolCall(
                    id="call_sys_1",
                    name="get_system_stats",
                    arguments={},
                )
            ],
            finish_reason="tool_calls",
        ),
        ProviderResponse(
            content="Your system is running smoothly with ample memory headroom.",
            model="mock-hermes-v2",
            tool_calls=[],
            finish_reason="stop",
        ),
    ]

    engine = build_test_engine(mock_responses)
    app = create_app(engine=engine)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        # Send user message
        ws.send_json({
            "type": "user_message",
            "content": "Check my computer performance.",
            "task": "fast_chat",
        })

        received_events: List[Dict[str, Any]] = []

        # Read streaming events until 'completed'
        while True:
            event = ws.receive_json()
            received_events.append(event)
            event_type = event.get("type")
            stage = event.get("stage", "")

            if event_type == "status" and stage == "completed":
                break
            if event_type == "error":
                raise AssertionError(f"Unexpected error event from WebSocket: {event}")

        event_types = [e.get("type") for e in received_events]
        stages = [e.get("stage") for e in received_events if e.get("type") == "status"]

        print(f"  Received {len(received_events)} streaming WebSocket events:")
        for idx, ev in enumerate(received_events, 1):
            detail = ev.get("stage") or ev.get("name") or ev.get("content") or ""
            print(f"    [{idx}] type='{ev.get('type')}', detail='{detail}'")

        # Assertions
        assert "planning" in stages, "Expected 'planning' status stage"
        assert "tool_call" in event_types, "Expected 'tool_call' event"
        assert "tool_result" in event_types, "Expected 'tool_result' event"
        assert "message" in event_types, "Expected final 'message' event"
        assert "completed" in stages, "Expected 'completed' status stage"

        # Verify tool call event structure
        tool_call_ev = next(e for e in received_events if e["type"] == "tool_call")
        assert tool_call_ev["name"] == "get_system_stats"

        # Verify tool result event structure
        tool_result_ev = next(e for e in received_events if e["type"] == "tool_result")
        assert tool_result_ev["name"] == "get_system_stats"
        assert "cpu" in tool_result_ev["result"]

        # Verify final message event structure
        msg_ev = next(e for e in received_events if e["type"] == "message")
        assert "running smoothly" in msg_ev["content"]

        print("  [PASS] WebSocket streaming verified: planning -> tool_call -> tool_result -> message -> completed.")


def main():
    print("Starting Standalone Verification Test Suite for FastAPI & WebSocket Bridge...")
    t0 = time.time()

    test_health_endpoint()
    test_system_status_endpoint()
    test_tools_endpoint()
    test_chat_endpoint()
    test_websocket_ping_pong()
    test_websocket_agent_streaming()

    elapsed = round(time.time() - t0, 2)
    print("\n" + "=" * 60)
    print(f"ALL API & WEBSOCKET TESTS PASSED SUCCESSFULLY in {elapsed}s (Exit Code: 0)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
