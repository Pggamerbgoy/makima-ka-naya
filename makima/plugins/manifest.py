"""Plugin Manifest and type definitions for Makima Extensibility Hub."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class PluginKind(str, Enum):
    LOCAL = "local"
    MCP_STDIO = "mcp_stdio"
    MCP_SSE = "mcp_sse"
    OPENAPI = "openapi"


@dataclass
class PluginManifest:
    name: str
    kind: str = "local"
    enabled: bool = True
    trusted: bool = True
    id: Optional[str] = None
    description: str = ""
    icon: Optional[str] = None
    version: str = "1.0.0"
    author: Optional[str] = None
    homepage: Optional[str] = None
    
    # For local python plugins:
    module: Optional[str] = None
    
    # For mcp_stdio:
    command: Optional[str] = None
    args: tuple[str, ...] = ()
    env: Optional[Dict[str, str]] = None
    
    # For mcp_sse:
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    
    # For openapi (ChatGPT plugins & GPT Actions):
    spec_url: Optional[str] = None
    spec_raw: Optional[Dict[str, Any]] = None
    base_url: Optional[str] = None
    auth_type: str = "none"  # "none", "bearer", "api_key", "basic"
    auth_config: Dict[str, str] = field(default_factory=dict)
    
    # Telemetry & status:
    tools_count: int = 0
    health: str = "ready"
    last_error: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", self.name)
        if isinstance(self.args, list):
            object.__setattr__(self, "args", tuple(self.args))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id or self.name,
            "name": self.name,
            "kind": self.kind,
            "enabled": self.enabled,
            "trusted": self.trusted,
            "description": self.description,
            "icon": self.icon,
            "version": self.version,
            "author": self.author,
            "homepage": self.homepage,
            "module": self.module,
            "command": self.command,
            "args": list(self.args),
            "env": self.env or {},
            "url": self.url,
            "headers": self.headers,
            "spec_url": self.spec_url,
            "spec_raw": self.spec_raw,
            "base_url": self.base_url,
            "auth_type": self.auth_type,
            "auth_configured": bool(self.auth_config and any(self.auth_config.values())),
            "tools_count": self.tools_count,
            "health": self.health,
            "last_error": self.last_error,
        }
