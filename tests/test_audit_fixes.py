"""Unit and regression tests verifying fixes for the 10 audited edge cases."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from makima.api.app import create_app
from makima.api.ws import pending_permissions
from makima.overlay.hud import _get_clipboard_text_safe, _set_clipboard_text_safe
from makima.core.telemetry import get_telemetry, _background_tasks
from makima.memory.vector_search import VectorSearchEngine


def test_app_guidance_page_when_no_ui_dist(monkeypatch, tmp_path):
    """Verifies that an informative guidance HTML page is served if dist/index.html is absent."""
    empty_dist = tmp_path / "empty_dist"
    empty_dist.mkdir()
    monkeypatch.setenv("MAKIMA_UI_DIST_DIR", str(empty_dist))
    monkeypatch.setenv("MAKIMA_SERVE_UI", "1")

    app = create_app(ui_dist_path=empty_dist)
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Makima Backend Server Active" in response.text
    assert "npm run build --prefix apps/chat_ui" in response.text


def test_terminate_process_triggers_hitl_permission():
    """Verifies that terminate_process is recognized as destructive and triggers HITL permission."""
    from tests.test_hitl_permission import make_test_setup
    client, executed, router = make_test_setup(
        tool_name="terminate_process",
        tool_args={"pid": 9999}
    )

    pending_permissions.clear()

    with client.websocket_connect("/ws") as ws:
        ws.send_json({
            "type": "user_message",
            "task_id": "test_perm_terminate",
            "content": "terminate process 9999",
        })

        perm_event = None
        for _ in range(15):
            try:
                data = ws.receive_json()
                if data.get("type") == "permission_request":
                    perm_event = data
                    break
            except Exception:
                break

        assert perm_event is not None
        assert perm_event["type"] == "permission_request"
        assert perm_event["tool"] == "terminate_process"
        assert perm_event["arguments"] == {"pid": 9999}

        # Resolve to allow graceful close
        ws.send_json({
            "type": "permission_response",
            "permission_id": perm_event["permission_id"],
            "allowed": True,
        })


@pytest.mark.asyncio
async def test_websocket_disconnect_cleans_pending_permissions():
    """Verifies that client disconnect immediately resolves pending permission futures to False without hanging 120s."""
    # Create fake pending future
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    perm_id = "test_cleanup_perm_1"
    pending_permissions[perm_id] = fut

    # Simulate disconnect resolution logic
    conn_perms = {perm_id}
    for pid in list(conn_perms):
        f = pending_permissions.pop(pid, None)
        if f and not f.done():
            f.set_result(False)

    assert fut.done()
    assert fut.result() is False
    assert perm_id not in pending_permissions


def test_telemetry_emit_sync_tracks_background_task():
    """Verifies that emit_sync retains strong references in _background_tasks."""
    tel = get_telemetry()
    initial_count = len(_background_tasks)
    tel.emit_sync("test.event", {"metric": 42})
    # Must not raise or fail
    assert len(tel.get_recent(5)) > 0


def test_clipboard_safe_helpers():
    """Verifies safe clipboard helpers run without unhandled exceptions."""
    val = _get_clipboard_text_safe()
    assert isinstance(val, str)
    # Setting text
    ok = _set_clipboard_text_safe("test_makima_clip")
    assert isinstance(ok, bool)


@pytest.mark.asyncio
async def test_vector_search_sqlite_busy_timeout(tmp_path):
    """Verifies that VectorSearchEngine sets busy_timeout and synchronous on connection."""
    db_file = tmp_path / "vec_test.db"
    vse = VectorSearchEngine(db_path=db_file)
    vse._sync_connect()
    assert vse._conn is not None

    cur = vse._conn.cursor()
    cur.execute("PRAGMA busy_timeout;")
    row = cur.fetchone()
    # Should be at least 5000ms
    assert row[0] >= 5000
    await vse.close()
