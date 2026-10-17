"""Tests for Claude Desktop configuration importer."""

from __future__ import annotations

import json
from makima.plugins.importer import import_claude_desktop_config


def test_import_claude_desktop_config() -> None:
    claude_cfg = {
        "mcpServers": {
            "sqlite": {
                "command": "uvx",
                "args": ["mcp-server-sqlite", "--db-path", "test.db"],
                "env": {"SQLITE_MODE": "ro"}
            },
            "remote_docs": {
                "url": "https://mcp.docs.example.com/sse",
                "headers": {"X-Auth": "abc"}
            }
        }
    }

    manifests = import_claude_desktop_config(claude_cfg)
    assert len(manifests) == 2
    
    sqlite_m = next(m for m in manifests if m.name == "sqlite")
    assert sqlite_m.kind == "mcp_stdio"
    assert sqlite_m.command == "uvx"
    assert sqlite_m.args == ("mcp-server-sqlite", "--db-path", "test.db")
    assert sqlite_m.env == {"SQLITE_MODE": "ro"}

    remote_m = next(m for m in manifests if m.name == "remote_docs")
    assert remote_m.kind == "mcp_sse"
    assert remote_m.url == "https://mcp.docs.example.com/sse"
