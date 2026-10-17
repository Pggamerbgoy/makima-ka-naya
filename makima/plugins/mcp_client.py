"""MCP Client adapter for stdio and sse Model Context Protocol servers."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from makima.plugins.manifest import PluginManifest
from makima.tools.registry import Tool, ToolRegistry

logger = logging.getLogger("makima.plugins.mcp")


class MCPManager:
    """Manages active MCP client connections across stdio and sse."""

    def __init__(self) -> None:
        self._stack: Optional[AsyncExitStack] = None
        self._clients: Dict[str, Any] = {}
        self._registered_tools: Dict[str, List[str]] = {}

    async def _ensure_stack(self) -> AsyncExitStack:
        if self._stack is None:
            self._stack = AsyncExitStack()
            await self._stack.__aenter__()
        return self._stack

    async def connect_manifest(self, manifest: PluginManifest, registry: ToolRegistry) -> List[str]:
        """Connects an MCP manifest (stdio or sse) and registers tools."""
        try:
            from mcp import Client, StdioServerParameters
        except ImportError:
            logger.info("mcp python library is not installed; skipping MCP plugin %s", manifest.name)
            return []

        stack = await self._ensure_stack()
        tools_loaded: List[str] = []

        try:
            if manifest.kind == "mcp_stdio" or (manifest.command and not manifest.url):
                if not manifest.command:
                    return []
                server = StdioServerParameters(
                    command=manifest.command,
                    args=list(manifest.args),
                    env=manifest.env,
                )
                client = await stack.enter_async_context(Client(server))
            elif manifest.kind == "mcp_sse" and manifest.url:
                try:
                    from mcp.client.sse import sse_client
                    client = await stack.enter_async_context(sse_client(manifest.url, headers=manifest.headers))
                except (ImportError, AttributeError):
                    logger.warning("MCP SSE transport not available in current mcp version.")
                    return []
            else:
                return []

            listed = await client.list_tools()
            self._clients[manifest.name] = client
            tool_names: List[str] = []

            for remote_tool in listed.tools:
                name = f"mcp_{manifest.name}_{remote_tool.name}"

                async def invoke(
                    arguments: Optional[Dict[str, Any]] = None,
                    *,
                    _client=client,
                    _name=remote_tool.name,
                ) -> Any:
                    result = await _client.call_tool(_name, arguments or {})
                    if getattr(result, "structured_content", None) is not None:
                        return result.structured_content
                    return "\n".join(str(item) for item in getattr(result, "content", []))

                schema = getattr(remote_tool, "inputSchema", None) or {"type": "object", "properties": {}}
                registry.register_tool(Tool(
                    name=name,
                    description=str(getattr(remote_tool, "description", "") or remote_tool.name),
                    fn=invoke,
                    tags=["plugin", "mcp", manifest.name],
                    parameters_schema=schema,
                    is_async=True,
                ))
                tool_names.append(name)
                tools_loaded.append(name)

            self._registered_tools[manifest.name] = tool_names
            return tools_loaded
        except Exception as exc:
            logger.warning("MCP server '%s' failed to connect: %s", manifest.name, exc)
            return []

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._clients.clear()
            self._registered_tools.clear()
