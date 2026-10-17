"""Tests for Plugin REST Endpoints Contract."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

from makima.api import create_app
from makima.plugins import PluginManager
from makima.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_plugin_rest_api_lifecycle(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True)

    pm = PluginManager(plugins_dir)
    app = create_app(
        plugin_manager=pm,
        ui_state_path=tmp_path / "ui_state.json",
        session_db_path=tmp_path / "sessions.sqlite3",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Get Catalog
        res = await client.get("/api/plugins/catalog")
        assert res.status_code == 200
        catalog = res.json()["catalog"]
        assert len(catalog) >= 3

        # 2. List initial plugins (empty)
        res = await client.get("/api/plugins")
        assert res.status_code == 200
        assert res.json()["count"] == 0

        # 3. Install an OpenAPI plugin from catalog
        open_meteo = next(item for item in catalog if item["id"] == "open_meteo")
        res = await client.post("/api/plugins/install", json=open_meteo)
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["plugin"]["name"] == "Open-Meteo Weather"

        # 4. Verify listed
        res = await client.get("/api/plugins")
        assert res.status_code == 200
        assert res.json()["count"] == 1
        plugin_item = res.json()["plugins"][0]
        assert plugin_item["id"] == "open_meteo"
        assert plugin_item["enabled"] is True

        # 5. Toggle plugin disabled
        res = await client.post("/api/plugins/open_meteo/toggle", json={"enabled": False})
        assert res.status_code == 200
        assert res.json()["enabled"] is False

        # 6. Configure credentials
        res = await client.post(
            "/api/plugins/open_meteo/configure",
            json={"token": "sample-secret-key-999", "header_name": "X-Custom-Key"},
        )
        assert res.status_code == 200
        assert res.json()["ok"] is True
        # Verify secret token is NOT leaked in response
        assert "sample-secret-key-999" not in json.dumps(res.json()["plugin"])

        # 7. Import Claude Desktop Config
        claude_cfg = {
            "mcpServers": {
                "sqlite_imported": {
                    "command": "uvx",
                    "args": ["mcp-server-sqlite"],
                }
            }
        }
        res = await client.post("/api/plugins/import/claude", json={"config": claude_cfg})
        assert res.status_code == 200
        assert res.json()["imported_count"] == 1

        # 8. Uninstall plugin
        res = await client.delete("/api/plugins/open_meteo")
        assert res.status_code == 200
        assert res.json()["ok"] is True

        res = await client.get("/api/plugins")
        assert res.status_code == 200
        # Only the imported claude plugin should remain
        assert res.json()["count"] == 1
        assert res.json()["plugins"][0]["name"] == "sqlite_imported"
