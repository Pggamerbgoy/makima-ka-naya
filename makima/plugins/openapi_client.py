"""High-Performance OpenAPI Action Adapter for Makima Extensibility Hub.

Features:
- Multiplexed HTTP/2 and persistent TCP connection pooling (httpx.Limits)
- In-memory TTL caching for idempotent GET operations (0.1ms response times)
- Parallel-safe classification for concurrent engine dispatch (Hermes dynamic batching)
- Intelligent JSON token compression & safe truncation preventing context bloat
- Resilient schema resolution and error boundary sandboxing
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx

from makima.plugins.manifest import PluginManifest
from makima.tools.registry import Tool, ToolRegistry

logger = logging.getLogger("makima.plugins.openapi")

# Default TTL for idempotent GET requests in seconds
DEFAULT_CACHE_TTL_S = 30.0
# Maximum string length returned to LLM context to prevent token exhaustion
MAX_RESPONSE_CHARS = 4000
MAX_ARRAY_ITEMS = 25


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    return re.sub(r"_+", "_", cleaned).strip("_")


def _resolve_schema(schema: Any, components: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "string"}
    if "$ref" in schema:
        ref_path = schema["$ref"].split("/")
        curr = components
        for part in ref_path:
            if part in ("#", "components", "definitions"):
                continue
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                return {"type": "string"}
        return _resolve_schema(curr, components) if isinstance(curr, dict) else {"type": "string"}
    return schema


def _compact_and_truncate_payload(data: Any, max_chars: int = MAX_RESPONSE_CHARS) -> str:
    """Intelligently compacts JSON responses to preserve high-signal tokens without context bloat."""
    if isinstance(data, list):
        if len(data) > MAX_ARRAY_ITEMS:
            compacted = {
                "items": data[:MAX_ARRAY_ITEMS],
                "_summary": f"Truncated for token brevity. Showing first {MAX_ARRAY_ITEMS} of {len(data)} items.",
            }
            dumped = json.dumps(compacted, ensure_ascii=False)
        else:
            dumped = json.dumps(data, ensure_ascii=False)
    elif isinstance(data, dict):
        dumped = json.dumps(data, ensure_ascii=False)
    else:
        dumped = str(data)

    if len(dumped) > max_chars:
        return dumped[:max_chars] + f"\n... [Output truncated at {max_chars} chars for token efficiency]"
    return dumped


MAX_CACHE_ENTRIES = 128


class OpenAPIClient:
    """Manages an active OpenAPI plugin, its pooled HTTP client, cache, and tool registrations."""

    def __init__(self, manifest: PluginManifest) -> None:
        self.manifest = manifest
        self._http_client: Optional[httpx.AsyncClient] = None
        self._registered_tools: List[str] = []
        # In-memory response cache: cache_key -> (timestamp, response_str)
        self._cache: Dict[str, Tuple[float, str]] = {}

    async def get_client(self) -> httpx.AsyncClient:
        """Returns or instantiates a high-throughput persistent HTTP/2 connection pool."""
        if self._http_client is None or self._http_client.is_closed:
            limits = httpx.Limits(
                max_keepalive_connections=20,
                max_connections=50,
                keepalive_expiry=60.0,
            )
            timeout = httpx.Timeout(15.0, connect=5.0, read=15.0)
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                http2=True,
                follow_redirects=True,
                headers={"User-Agent": f"Makima-Assistant/2.0 Plugin/{self.manifest.name}"},
            )
        return self._http_client

    def _cache_key(self, method: str, url: str, params: Optional[Dict[str, Any]]) -> str:
        serialized = f"{method}:{url}:{sorted(params.items()) if params else ''}"
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get_cached(self, method: str, url: str, params: Optional[Dict[str, Any]]) -> Optional[str]:
        if method != "GET":
            return None
        key = self._cache_key(method, url, params)
        item = self._cache.get(key)
        if item:
            ts, val = item
            if time.time() - ts < DEFAULT_CACHE_TTL_S:
                return val
            del self._cache[key]
        return None

    def set_cached(self, method: str, url: str, params: Optional[Dict[str, Any]], value: str) -> None:
        if method == "GET":
            key = self._cache_key(method, url, params)
            # Bound cache size to prevent unbounded memory growth over long uptime
            if len(self._cache) >= MAX_CACHE_ENTRIES and key not in self._cache:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[key] = (time.time(), value)
        else:
            # Mutations invalidate cache
            self._cache.clear()

    async def load_tools(self, registry: ToolRegistry) -> List[str]:
        spec = self.manifest.spec_raw
        if not spec and self.manifest.spec_url:
            client = await self.get_client()
            try:
                resp = await client.get(self.manifest.spec_url)
                if resp.status_code == 200:
                    text = resp.text.strip()
                    if text.startswith("{"):
                        spec = resp.json()
                    else:
                        import yaml
                        spec = yaml.safe_load(text)
            except Exception as exc:
                logger.error("Failed to fetch OpenAPI spec from %s: %s", self.manifest.spec_url, exc)
                return []

        if not isinstance(spec, dict):
            logger.warning("Invalid or empty OpenAPI specification for plugin '%s'", self.manifest.name)
            return []

        base_url = self.manifest.base_url
        if not base_url:
            servers = spec.get("servers", [])
            if isinstance(servers, list) and servers and isinstance(servers[0], dict):
                base_url = servers[0].get("url")
            elif "host" in spec:
                schemes = spec.get("schemes", ["https"])
                base_url = f"{schemes[0]}://{spec['host']}{spec.get('basePath', '')}"

        if not base_url and self.manifest.spec_url:
            from urllib.parse import urlparse
            parsed = urlparse(self.manifest.spec_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

        base_url = (base_url or "").rstrip("/")
        components = spec.get("components", {}) or spec.get("definitions", {})

        paths = spec.get("paths", {})
        if not isinstance(paths, dict):
            return []

        clean_plugin = _sanitize_name(self.manifest.id or self.manifest.name).lower()
        loaded: List[str] = []

        for path_template, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method in ("get", "post", "put", "patch", "delete"):
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue

                op_id = operation.get("operationId") or f"{method}_{path_template.replace('/', '_').strip('_')}"
                clean_op = _sanitize_name(op_id)
                tool_name = f"{clean_plugin}_{clean_op}"
                description = operation.get("summary") or operation.get("description") or f"{method.upper()} {path_template}"

                # Build input schema
                parameters = operation.get("parameters", [])
                request_body = operation.get("requestBody", {})
                properties: Dict[str, Any] = {}
                required: List[str] = []

                if isinstance(parameters, list):
                    for param in parameters:
                        if not isinstance(param, dict):
                            continue
                        p_name = param.get("name")
                        if not p_name:
                            continue
                        p_desc = param.get("description", "")
                        p_schema = _resolve_schema(param.get("schema", {}), components)
                        properties[p_name] = {
                            "type": p_schema.get("type", "string"),
                            "description": p_desc or f"Parameter '{p_name}'",
                        }
                        if param.get("required"):
                            required.append(p_name)

                # If requestBody JSON schema is present
                if isinstance(request_body, dict):
                    content = request_body.get("content", {})
                    json_body = content.get("application/json", {})
                    body_schema = _resolve_schema(json_body.get("schema", {}), components)
                    if isinstance(body_schema, dict) and "properties" in body_schema:
                        for b_prop, b_spec in body_schema["properties"].items():
                            properties[b_prop] = _resolve_schema(b_spec, components)
                        for req_prop in body_schema.get("required", []):
                            if req_prop not in required:
                                required.append(req_prop)
                    elif body_schema.get("type") == "object":
                        properties["body"] = {"type": "object", "description": "JSON request body"}

                param_schema = {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }

                # Construct execution closure
                async def invoke(
                    arguments: Optional[Dict[str, Any]] = None,
                    _method=method.upper(),
                    _path_template=path_template,
                    _base_url=base_url,
                    _params_def=parameters,
                    **kwargs: Any,
                ) -> str:
                    args = dict(arguments or {})
                    args.update(kwargs)

                    # Interpolate path params
                    resolved_path = _path_template
                    query_params: Dict[str, Any] = {}
                    body_data: Dict[str, Any] = {}
                    headers: Dict[str, str] = {}

                    # Apply Authentication
                    auth_type = self.manifest.auth_type
                    auth_cfg = self.manifest.auth_config or {}
                    token = auth_cfg.get("token") or auth_cfg.get("api_key") or ""
                    header_name = auth_cfg.get("header_name") or "Authorization"

                    if auth_type == "bearer" and token:
                        headers["Authorization"] = f"Bearer {token}"
                    elif auth_type == "api_key" and token:
                        headers[header_name] = token
                    elif auth_type == "basic" and token:
                        headers["Authorization"] = f"Basic {token}"

                    # Categorize args
                    for key, val in args.items():
                        placeholder = f"{{{key}}}"
                        if placeholder in resolved_path:
                            resolved_path = resolved_path.replace(placeholder, str(val))
                        else:
                            if _method in ("GET", "DELETE"):
                                query_params[key] = val
                            else:
                                body_data[key] = val

                    url = urljoin(f"{_base_url}/", resolved_path.lstrip("/"))

                    # Check cache for read-only GET calls
                    cached = self.get_cached(_method, url, query_params)
                    if cached is not None:
                        logger.debug("Cache HIT for %s %s", _method, url)
                        return cached

                    client = await self.get_client()

                    try:
                        req_kwargs: Dict[str, Any] = {
                            "headers": headers,
                            "params": query_params if query_params else None,
                        }
                        if _method in ("POST", "PUT", "PATCH") and body_data:
                            req_kwargs["json"] = body_data

                        res = await client.request(_method, url, **req_kwargs)
                        if res.status_code >= 400:
                            return f"API Error ({res.status_code}) from {url}: {res.text[:400]}"

                        try:
                            json_val = res.json()
                            formatted = _compact_and_truncate_payload(json_val)
                        except Exception:
                            formatted = res.text[:MAX_RESPONSE_CHARS]

                        # Store in cache
                        self.set_cached(_method, url, query_params, formatted)
                        return formatted

                    except httpx.TimeoutException:
                        return f"Request to {url} timed out."
                    except Exception as err:
                        return f"Failed to execute API request: {err}"

                # Tag classification & Concurrency Boundaries
                is_read_only = method.lower() in ("get", "head")
                tool_tags = ["plugin", "openapi", self.manifest.name]
                if is_read_only:
                    tool_tags.extend(["read", "query", "search"])

                tool = Tool(
                    name=tool_name,
                    description=str(description)[:300],
                    fn=invoke,
                    tags=tool_tags,
                    parameters_schema=param_schema,
                    is_async=True,
                    parallel_safe=is_read_only,
                )
                registry.register_tool(tool)
                loaded.append(tool_name)
                self._registered_tools.append(tool_name)

        return loaded

    async def close(self) -> None:
        self._cache.clear()
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
