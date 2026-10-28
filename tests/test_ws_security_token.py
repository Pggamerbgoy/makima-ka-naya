"""
Tests WebSocket security token enforcement for non-browser clients (P0-6).
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from makima.api.app import create_app


def test_ws_security_token_enforcement(monkeypatch, tmp_path):
    monkeypatch.setenv("MAKIMA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MAKIMA_REQUIRE_WS_TOKEN", "1")
    monkeypatch.setenv("MAKIMA_AUTH_TOKEN", "test-secret-token-1234567890abcdef")

    app = create_app()
    client = TestClient(app)

    # 1. Non-browser client without origin or token should be rejected (code 1008)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws"):
            pass
    assert exc_info.value.code == 1008

    # 2. Non-browser client with wrong token should be rejected
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws?token=wrong_token"):
            pass
    assert exc_info.value.code == 1008

    # 3. Non-browser client with correct query param token should connect successfully
    with client.websocket_connect("/ws?token=test-secret-token-1234567890abcdef") as ws:
        ws.send_json({"type": "ping"})
        msg = ws.receive_json()
        assert msg.get("type") == "pong"

    # 4. Non-browser client with correct header should connect successfully
    with client.websocket_connect("/ws", headers={"x-makima-token": "test-secret-token-1234567890abcdef"}) as ws:
        ws.send_json({"type": "ping"})
        msg = ws.receive_json()
        assert msg.get("type") == "pong"
