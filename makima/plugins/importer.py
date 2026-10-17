"""Configuration and Specification Importers for Makima Extensibility Hub."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

from makima.plugins.manifest import PluginKind, PluginManifest

logger = logging.getLogger("makima.plugins.importer")


def import_claude_desktop_config(config_source: Union[str, Dict[str, Any]]) -> List[PluginManifest]:
    """Imports Claude Desktop configuration (claude_desktop_config.json) into PluginManifests."""
    data: Dict[str, Any] = {}
    if isinstance(config_source, str):
        try:
            data = json.loads(config_source.strip())
        except Exception as exc:
            logger.error("Failed to parse Claude Desktop config JSON: %s", exc)
            return []
    elif isinstance(config_source, dict):
        data = config_source

    servers = data.get("mcpServers") or data.get("servers") or {}
    if not isinstance(servers, dict):
        return []

    manifests: List[PluginManifest] = []
    for server_name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        command = spec.get("command")
        url = spec.get("url")
        args = tuple(str(a) for a in spec.get("args", []))
        env = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}

        kind = PluginKind.MCP_SSE.value if url else PluginKind.MCP_STDIO.value
        manifests.append(PluginManifest(
            id=f"claude_{server_name}",
            name=server_name,
            kind=kind,
            enabled=True,
            trusted=True,
            description=f"Imported from Claude Desktop ({server_name})",
            command=command,
            args=args,
            env=env or None,
            url=url,
        ))

    return manifests


def import_openapi_manifest(
    name: str,
    spec_url_or_raw: Union[str, Dict[str, Any]],
    base_url: Optional[str] = None,
    auth_type: str = "none",
    token: Optional[str] = None,
    header_name: str = "Authorization",
    description: str = "",
) -> PluginManifest:
    """Creates an OpenAPI PluginManifest."""
    spec_url: Optional[str] = None
    spec_raw: Optional[Dict[str, Any]] = None

    if isinstance(spec_url_or_raw, str):
        if spec_url_or_raw.startswith(("http://", "https://")):
            spec_url = spec_url_or_raw
        else:
            try:
                spec_raw = json.loads(spec_url_or_raw)
            except Exception:
                spec_url = spec_url_or_raw
    else:
        spec_raw = spec_url_or_raw

    auth_config: Dict[str, str] = {}
    if token:
        auth_config["token"] = token
        auth_config["header_name"] = header_name

    return PluginManifest(
        id=name.lower().replace(" ", "_"),
        name=name,
        kind=PluginKind.OPENAPI.value,
        enabled=True,
        trusted=True,
        description=description or f"OpenAPI REST Actions for {name}",
        spec_url=spec_url,
        spec_raw=spec_raw,
        base_url=base_url,
        auth_type=auth_type,
        auth_config=auth_config,
    )
