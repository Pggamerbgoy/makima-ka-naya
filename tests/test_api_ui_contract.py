"""Fast, deterministic contract tests for the browser UI backend surface."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import os

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from makima.api.app import create_app
from makima.core.engine import HermesAgentEngine
from makima.provider.adapters.base import Message, ProviderResponse, ToolCall
from makima.provider.router import ParetoRouter
from makima.tools.registry import ToolRegistry


class ContractRouter(ParetoRouter):
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
        prompt = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return ProviderResponse(content=f"contract echo: {prompt}", model="contract-model", finish_reason="stop")


def make_client(state_path: Path | None = None, ui_dist_path: Path | None = None) -> TestClient:
    registry = ToolRegistry()
    registry.register(lambda query: query, name="search_demo", description="Search demo data", tags=["search"])
    return TestClient(create_app(engine=HermesAgentEngine(router=ContractRouter()), registry=registry, ui_state_path=state_path, ui_dist_path=ui_dist_path))


def test_local_static_ui_and_origin_guards(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Makima</title>", encoding="utf-8")
    client = make_client(tmp_path / "ui_state.json", dist)
    assert client.get("/").status_code == 200
    assert "Makima" in client.get("/").text
    allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
    blocked = client.get("/health", headers={"Origin": "https://evil.example"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in blocked.headers
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}):
            pass


def test_settings_connectors_and_tools_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAKIMA_ENV_FILE", str(tmp_path / ".env.test"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE", raising=False)
    client = make_client(tmp_path / "ui_state.json")
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    assert settings.json()["settings"]["max_turns"] in (15, 30)

    saved = client.post("/api/settings", json={"temperature": 0.2, "theme": "light"})
    assert saved.status_code == 200
    assert saved.json()["settings"]["theme"] == "light"
    assert client.post("/api/settings", json={"theme": "neon"}).status_code == 422
    restarted = make_client(tmp_path / "ui_state.json")
    assert restarted.get("/api/settings").json()["settings"]["theme"] == "light"

    connectors = client.get("/api/connectors").json()["connectors"]
    assert {item["id"] for item in connectors} >= {"whatsapp", "github", "gdrive", "spotify", "figma"}
    assert all(item["configured"] is False for item in connectors)
    toggled = client.post("/api/connectors/github", json={"enabled": True})
    assert toggled.status_code == 200 and toggled.json()["connector"]["enabled"] is True

    tools = client.get("/api/tools").json()["tools"]
    assert tools[0]["enabled"] is True and tools[0]["category"] == "search"
    disabled = client.post("/api/tools/search_demo/enabled", json={"enabled": False})
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False

    connector_check = client.post("/api/connectors/github/check")
    assert connector_check.status_code == 200
    assert connector_check.json()["connector"]["health"] == "not_configured"
    assert connector_check.json()["ok"] is False

    # Test configure and disconnect endpoints
    configured = client.post("/api/connectors/whatsapp/configure", json={"credential": "+1234567890"})
    assert configured.status_code == 200
    assert configured.json()["ok"] is True
    assert configured.json()["connector"]["configured"] is True
    assert configured.json()["connector"]["health"] == "ready"

    disconnected = client.post("/api/connectors/whatsapp/disconnect")
    assert disconnected.status_code == 200
    assert disconnected.json()["ok"] is True
    assert disconnected.json()["connector"]["configured"] is False
    tool_check = client.post("/api/tools/search_demo/check")
    assert tool_check.status_code == 200
    assert tool_check.json()["status"] == "disabled"

    voice = client.get("/api/voice/capabilities")
    assert voice.status_code == 200
    assert voice.json()["credentials_exposed"] is False
    assert voice.json()["model"]

    diagnostics = client.get("/api/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["credentials_exposed"] is False


def test_status_and_correlated_websocket_message(tmp_path: Path):
    client = make_client(tmp_path / "ui_state.json")
    status = client.get("/api/status")
    assert status.status_code == 200
    assert "backends" in status.json()["providers"]

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_message", "task_id": "ui-contract-1", "content": "hello"})
        seen = []
        for _ in range(8):
            event = ws.receive_json()
            seen.append(event)
            if event["type"] == "message":
                break
        assert any(event["type"] == "status" and event["task_id"] == "ui-contract-1" for event in seen)
        final = next(event for event in seen if event["type"] == "message")
        assert final["task_id"] == "ui-contract-1"
        assert final["content"] == "contract echo: hello"

    with client.websocket_connect("/ws") as ws:
        ws.send_json({
            "type": "user_message",
            "task_id": "ui-attachment-1",
            "content": "Summarize this file",
            "attachments": [{"name": "notes.md", "mime_type": "text/markdown", "size": 18, "text_preview": "# Release notes\nReady"}],
        })
        seen = []
        for _ in range(8):
            event = ws.receive_json()
            seen.append(event)
            if event["type"] == "message":
                break
        final = next(event for event in seen if event["type"] == "message")
        assert "# Release notes" in final["content"]


def test_voice_bridge_control_ping_does_not_expose_credentials(tmp_path: Path):
    client = make_client(tmp_path / "ui_state.json")
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "ping"})
        event = ws.receive_json()
        assert event["type"] == "voice_pong"
        assert "api_key" not in event


def test_connector_persistence_across_restart(tmp_path: Path, monkeypatch):
    test_env = tmp_path / ".env"
    monkeypatch.setenv("MAKIMA_ENV_FILE", str(test_env))
    ui_state = tmp_path / "ui_state.json"

    # 1. Start Makima, configure WhatsApp
    client1 = make_client(ui_state)
    res = client1.post("/api/connectors/whatsapp/configure", json={"credential": "+919876543210"})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["connector"]["configured"] is True

    # 2. Verify .env file was created and contains the credential
    assert test_env.exists()
    env_content = test_env.read_text(encoding="utf-8")
    assert "+919876543210" in env_content

    # 3. Clear memory to simulate full process termination
    monkeypatch.delenv("WHATSAPP_PHONE", raising=False)
    assert os.getenv("WHATSAPP_PHONE") is None

    # 4. Simulate server restart: create brand-new app instance
    client2 = make_client(ui_state)
    connectors = client2.get("/api/connectors").json()["connectors"]
    whatsapp = next(c for c in connectors if c["id"] == "whatsapp")

    # Connector should be ALREADY CONFIGURED and ready across restart!
    assert whatsapp["configured"] is True
    assert whatsapp["health"] == "ready"
    assert os.getenv("WHATSAPP_PHONE") == "+919876543210"

    # 5. Clean disconnect removes from both memory and .env
    disc_res = client2.post("/api/connectors/whatsapp/disconnect")
    assert disc_res.status_code == 200
    assert disc_res.json()["connector"]["configured"] is False
    assert os.getenv("WHATSAPP_PHONE") is None
    assert "+919876543210" not in test_env.read_text(encoding="utf-8")


def test_cors_preflight_allows_delete_and_patch(tmp_path: Path):
    client = make_client(tmp_path / "ui_state.json")
    # Preflight for DELETE /api/sessions/xyz from Vite dev origin
    res = client.options(
        "/api/sessions/test_session_id",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.status_code == 200
    assert "DELETE" in res.headers.get("access-control-allow-methods", "")
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"




def test_rest_chat_respects_disabled_tool_gateway(tmp_path: Path) -> None:
    executions: list[dict[str, Any]] = []
    registry = ToolRegistry()

    def destructive_demo(target: str) -> dict[str, Any]:
        executions.append({"target": target})
        return {"success": True}

    registry.register(
        destructive_demo,
        name="destructive_demo",
        description="Test-only action that must not run while disabled.",
        tags=["control"],
    )

    router = ContractRouter()
    router.queued_responses = [
        ProviderResponse(
            content="",
            model="contract-model",
            tool_calls=[
                ToolCall(
                    id="disabled-rest-call",
                    name="destructive_demo",
                    arguments={"target": "must-not-run"},
                )
            ],
            finish_reason="tool_calls",
        ),
        ProviderResponse(
            content="The disabled action was not executed.",
            model="contract-model",
            finish_reason="stop",
        ),
    ]
    engine = HermesAgentEngine(router=router)
    client = TestClient(
        create_app(
            engine=engine,
            registry=registry,
            ui_state_path=tmp_path / "ui_state.json",
            ui_dist_path=tmp_path / "missing-dist",
        )
    )

    disabled = client.post("/api/tools/destructive_demo/enabled", json={"enabled": False})
    assert disabled.status_code == 200
    response = client.post("/api/chat", json={"prompt": "Run the test action."})

    assert response.status_code == 200, response.text
    assert executions == [], "REST chat must not bypass disabled tool state."
    tool_messages = [
        item.get("content", "")
        for item in response.json()["messages"]
        if item.get("role") == "tool"
    ]
    assert any("[TOOL_NOT_AVAILABLE: destructive_demo]" in value for value in tool_messages)
