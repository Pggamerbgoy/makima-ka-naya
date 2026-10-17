from __future__ import annotations

import json
from pathlib import Path

from makima.plugins import PluginManager
from makima.tools.registry import CapabilityToolRegistry, ToolRegistry


def test_chat_capability_profile_hides_high_impact_tools() -> None:
    registry = ToolRegistry()

    def read_status() -> str:
        return "ok"

    def execute_command(command: str) -> str:
        return command

    registry.register(read_status, name="read_status", tags=["system"])
    registry.register(execute_command, name="execute_command", tags=["terminal", "system"])

    scoped = CapabilityToolRegistry(registry, profile="chat")
    assert scoped.list_names() == ["read_status"]


def test_plugin_manager_reads_trust_and_enablement(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "example"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "example", "kind": "local", "enabled": False, "trusted": True, "module": "example"}),
        encoding="utf-8",
    )
    manifest = PluginManager(tmp_path / "plugins").manifests()[0]
    assert manifest.enabled is False
    assert manifest.trusted is True
