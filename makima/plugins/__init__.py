"""Makima Extensibility Hub — ChatGPT Plugins, OpenAPI Actions, and Claude MCP."""

from __future__ import annotations

from makima.plugins.catalog import fetch_external_catalog, get_marketplace_catalog
from makima.plugins.discovery import DiscoveryResult, discover_plugin_or_api
from makima.plugins.importer import import_claude_desktop_config, import_openapi_manifest
from makima.plugins.manager import PluginManager
from makima.plugins.manifest import PluginKind, PluginManifest
from makima.plugins.mcp_client import MCPManager
from makima.plugins.openapi_client import OpenAPIClient

__all__ = [
    "PluginKind",
    "PluginManifest",
    "PluginManager",
    "OpenAPIClient",
    "MCPManager",
    "DiscoveryResult",
    "discover_plugin_or_api",
    "import_claude_desktop_config",
    "import_openapi_manifest",
    "get_marketplace_catalog",
    "fetch_external_catalog",
]
