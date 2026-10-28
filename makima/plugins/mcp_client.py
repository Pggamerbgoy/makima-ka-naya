"""MCP Client adapter for stdio and sse Model Context Protocol servers."""

from __future__ import annotations

import logging
import re
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
            import os
            import shutil
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            logger.info("mcp python library is not installed; skipping MCP plugin %s", manifest.name)
            return []

        stack = await self._ensure_stack()
        tools_loaded: List[str] = []

        try:
            session = None
            if manifest.kind in ("mcp", "mcp_stdio") or (manifest.command and not manifest.url):
                if not manifest.command:
                    return []

                # Resolve executable for Windows (e.g. npx -> npx.cmd)
                cmd = shutil.which(manifest.command) or manifest.command

                # Prepare environment and auto-bridge known connector tokens
                env = os.environ.copy()
                if manifest.env:
                    env.update(manifest.env)

                # Auto-bridge GitHub token if this is a GitHub MCP plugin
                low_name = f"{manifest.name} {manifest.id}".lower()
                if any(k in low_name for k in ("github", "git")):
                    saved_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN") or ""
                    if saved_token:
                        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = saved_token
                        env["GITHUB_TOKEN"] = saved_token

                server = StdioServerParameters(
                    command=cmd,
                    args=list(manifest.args),
                    env=env,
                )
                read_stream, write_stream = await stack.enter_async_context(stdio_client(server))
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                await session.initialize()

            elif manifest.kind == "mcp_sse" and manifest.url:
                try:
                    from mcp.client.sse import sse_client
                    read_stream, write_stream = await stack.enter_async_context(sse_client(manifest.url, headers=manifest.headers))
                    session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                    await session.initialize()
                except (ImportError, AttributeError) as sse_err:
                    logger.warning("MCP SSE transport not available in current mcp version: %s", sse_err)
                    return []
            else:
                return []

            if session is None:
                return []

            listed = await session.list_tools()
            self._clients[manifest.name] = session
            tool_names: List[str] = []

            # Infer smart domain tags from manifest name/id so intent router routes queries here
            domain_tags = ["plugin", "mcp", manifest.name, manifest.id or ""]
            low_check = f"{manifest.name} {manifest.id} {manifest.description}".lower()
            if any(k in low_check for k in ("github", "git", "repo", "pull request")):
                domain_tags.extend(["github", "git", "developer", "repositories", "code"])
            elif any(k in low_check for k in ("sqlite", "sql", "database", "postgres", "db")):
                domain_tags.extend(["database", "sql", "sqlite", "query"])
            elif any(k in low_check for k in ("fetch", "web", "scrape", "markdown")):
                domain_tags.extend(["web", "fetch", "scrape", "markdown"])

            clean_prefix = re.sub(r"[^a-zA-Z0-9_]+", "_", manifest.id or manifest.name).strip("_")

            def make_invoker(target_session, target_name):
                async def invoke(*pos_args, **kwargs) -> Any:
                    call_args = dict(kwargs)
                    if pos_args and isinstance(pos_args[0], dict):
                        call_args.update(pos_args[0])
                    result = await target_session.call_tool(target_name, call_args)
                    if getattr(result, "structured_content", None) is not None:
                        return result.structured_content
                    text_parts = []
                    for item in getattr(result, "content", []):
                        if hasattr(item, "text"):
                            text_parts.append(item.text)
                        else:
                            text_parts.append(str(item))
                    return "\n".join(text_parts) if text_parts else "Success"
                return invoke

            for remote_tool in listed.tools:
                clean_tool_name = re.sub(r"[^a-zA-Z0-9_]+", "_", remote_tool.name).strip("_")
                name = f"mcp_{clean_prefix}_{clean_tool_name}"
                raw_schema = getattr(remote_tool, "inputSchema", None) or {"type": "object", "properties": {}}
                if isinstance(raw_schema, dict):
                    schema = {k: v for k, v in raw_schema.items() if not str(k).startswith("$")}
                else:
                    schema = raw_schema
                registry.register_tool(Tool(
                    name=name,
                    description=str(getattr(remote_tool, "description", "") or remote_tool.name),
                    fn=make_invoker(session, remote_tool.name),
                    tags=list(set(domain_tags)),
                    parameters_schema=schema,
                    is_async=True,
                ))
                tool_names.append(name)
                tools_loaded.append(name)

            self._registered_tools[manifest.name] = tool_names
            logger.info("Successfully connected MCP plugin '%s' with %d tools: %s", manifest.name, len(tools_loaded), tool_names)
            return tools_loaded
        except Exception as exc:
            logger.warning("MCP server '%s' failed to connect: %s", manifest.name, exc, exc_info=True)
            return []

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._clients.clear()
            self._registered_tools.clear()
