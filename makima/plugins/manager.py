"""Central Plugin Manager orchestrating manifest persistence, discovery, and tool registration."""

from __future__ import annotations

import importlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from makima.plugins.manifest import PluginKind, PluginManifest
from makima.plugins.mcp_client import MCPManager
from makima.plugins.openapi_client import OpenAPIClient
from makima.tools.registry import ToolRegistry

logger = logging.getLogger("makima.plugins.manager")


class PluginManager:
    """Loads, saves, and activates Makima plugins (Local, MCP Stdio, MCP SSE, OpenAPI Actions)."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.expanduser().resolve()
        self._mcp_manager = MCPManager()
        self._openapi_clients: Dict[str, OpenAPIClient] = {}
        self._active_tools: Dict[str, List[str]] = {}

    @property
    def secrets_path(self) -> Path:
        return self.directory / ".secrets.json"

    def _read_secrets(self) -> Dict[str, Dict[str, str]]:
        if not self.secrets_path.is_file():
            return {}
        try:
            return json.loads(self.secrets_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_secrets(self, secrets: Dict[str, Dict[str, str]]) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.secrets_path.write_text(json.dumps(secrets, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not persist plugin secrets: %s", exc)

    def manifests(self) -> List[PluginManifest]:
        if not self.directory.exists():
            return []
        result: List[PluginManifest] = []
        secrets = self._read_secrets()

        for path in sorted(self.directory.glob("*/plugin.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                plugin_id = str(raw.get("id") or raw["name"])
                
                # Merge persisted server-side secret if available
                auth_cfg = dict(raw.get("auth_config") or {})
                if plugin_id in secrets:
                    auth_cfg.update(secrets[plugin_id])

                manifest = PluginManifest(
                    name=str(raw["name"]),
                    kind=str(raw.get("kind", "local")),
                    enabled=bool(raw.get("enabled", False)),
                    trusted=bool(raw.get("trusted", False)),
                    id=plugin_id,
                    description=str(raw.get("description", "")),
                    icon=raw.get("icon"),
                    version=str(raw.get("version", "1.0.0")),
                    author=raw.get("author"),
                    homepage=raw.get("homepage"),
                    module=raw.get("module"),
                    command=raw.get("command"),
                    args=tuple(str(item) for item in raw.get("args", [])),
                    env={str(k): str(v) for k, v in (raw.get("env") or {}).items()} or None,
                    url=raw.get("url"),
                    headers=dict(raw.get("headers") or {}),
                    spec_url=raw.get("spec_url"),
                    spec_raw=raw.get("spec_raw"),
                    base_url=raw.get("base_url"),
                    auth_type=str(raw.get("auth_type", "none")),
                    auth_config=auth_cfg,
                    tools_count=len(self._active_tools.get(plugin_id, [])),
                    health=raw.get("health", "ready"),
                )
                result.append(manifest)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                logger.warning("Ignoring invalid plugin manifest %s: %s", path, exc)
        return result

    def get_manifest(self, plugin_id: str) -> Optional[PluginManifest]:
        for m in self.manifests():
            if m.id == plugin_id or m.name == plugin_id:
                return m
        return None

    def save_manifest(self, manifest: PluginManifest, secret_token: Optional[str] = None) -> PluginManifest:
        plugin_id = manifest.id or manifest.name
        folder = self.directory / plugin_id
        folder.mkdir(parents=True, exist_ok=True)

        # Separate secret token from publicly safe manifest
        safe_auth_cfg = dict(manifest.auth_config)
        if secret_token is not None:
            safe_auth_cfg["token"] = ""
            secrets = self._read_secrets()
            secrets.setdefault(plugin_id, {})["token"] = secret_token
            if manifest.auth_config.get("header_name"):
                secrets[plugin_id]["header_name"] = manifest.auth_config["header_name"]
            self._write_secrets(secrets)

        payload = manifest.to_dict()
        # Do not write actual secret token to plugin.json
        payload["auth_config"] = safe_auth_cfg
        (folder / "plugin.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return manifest

    def delete_manifest(self, plugin_id: str) -> bool:
        folder = self.directory / plugin_id
        deleted = False
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            deleted = True
        
        # Also clean up secrets
        secrets = self._read_secrets()
        if plugin_id in secrets:
            del secrets[plugin_id]
            self._write_secrets(secrets)
        
        if plugin_id in self._active_tools:
            del self._active_tools[plugin_id]
        if plugin_id in self._openapi_clients:
            del self._openapi_clients[plugin_id]

        return deleted

    def load_local(self, registry: ToolRegistry) -> List[str]:
        loaded: List[str] = []
        for manifest in self.manifests():
            if manifest.kind != "local" or not manifest.enabled or not manifest.trusted or not manifest.module:
                continue
            try:
                module = importlib.import_module(manifest.module)
                registry.discover(module)
                loaded.append(manifest.name)
            except Exception as exc:
                logger.warning("Plugin '%s' failed to load: %s", manifest.name, exc)
        return loaded

    async def connect_mcp(self, registry: ToolRegistry) -> List[str]:
        loaded_plugins: List[str] = []
        for manifest in self.manifests():
            if manifest.kind not in ("mcp", "mcp_stdio", "mcp_sse") or not manifest.enabled or not manifest.trusted:
                continue
            tools = await self._mcp_manager.connect_manifest(manifest, registry)
            if tools:
                self._active_tools[manifest.id or manifest.name] = tools
                loaded_plugins.append(manifest.name)
        return loaded_plugins

    async def load_all(self, registry: ToolRegistry) -> Dict[str, List[str]]:
        """Loads all enabled plugins (Local, MCP, and OpenAPI) into the ToolRegistry."""
        results: Dict[str, List[str]] = {}

        # 1. Local Python plugins
        self.load_local(registry)

        # 2. MCP plugins
        for manifest in self.manifests():
            if not manifest.enabled or not manifest.trusted:
                continue
            m_id = manifest.id or manifest.name

            if manifest.kind in ("mcp", "mcp_stdio", "mcp_sse") or (manifest.command and not manifest.spec_url):
                tools = await self._mcp_manager.connect_manifest(manifest, registry)
                if tools:
                    self._active_tools[m_id] = tools
                    results[m_id] = tools

            # 3. OpenAPI plugins (ChatGPT Plugins & Custom Actions)
            elif manifest.kind == PluginKind.OPENAPI.value or manifest.spec_url or manifest.spec_raw:
                try:
                    client = OpenAPIClient(manifest)
                    tools = await client.load_tools(registry)
                    self._openapi_clients[m_id] = client
                    self._active_tools[m_id] = tools
                    results[m_id] = tools
                except Exception as exc:
                    logger.error("Failed to load OpenAPI plugin %s: %s", m_id, exc)

        return results

    async def close(self) -> None:
        await self._mcp_manager.close()
        for client in self._openapi_clients.values():
            await client.close()
        self._openapi_clients.clear()
        self._active_tools.clear()
