"""Curated Marketplace Catalog for Makima Extensibility Hub."""

from __future__ import annotations

from typing import Any, Dict, List

MARKETPLACE_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "open_meteo",
        "name": "Open-Meteo Weather",
        "category": "Data & Environment",
        "kind": "openapi",
        "description": "Accurate worldwide weather forecast, temperature, humidity, wind, and precipitation. No API key needed.",
        "icon": "🌤️",
        "author": "Open-Meteo",
        "homepage": "https://open-meteo.com",
        "base_url": "https://api.open-meteo.com",
        "auth_type": "none",
        "spec_raw": {
            "openapi": "3.0.0",
            "info": {
                "title": "Open-Meteo Weather Forecast API",
                "version": "1.0.0",
                "description": "Seamless worldwide weather forecast."
            },
            "servers": [{"url": "https://api.open-meteo.com"}],
            "paths": {
                "/v1/forecast": {
                    "get": {
                        "operationId": "get_forecast",
                        "summary": "Get weather forecast by latitude and longitude",
                        "parameters": [
                            {"name": "latitude", "in": "query", "required": True, "schema": {"type": "number"}, "description": "Latitude (e.g. 35.6895 for Tokyo, 28.6139 for Delhi, 37.7749 for SF)"},
                            {"name": "longitude", "in": "query", "required": True, "schema": {"type": "number"}, "description": "Longitude (e.g. 139.6917 for Tokyo, 77.2090 for Delhi, -122.4194 for SF)"},
                            {"name": "current_weather", "in": "query", "required": False, "schema": {"type": "boolean"}, "description": "Include current weather summary (default: true)"},
                            {"name": "hourly", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Comma-separated hourly variables, e.g. temperature_2m,precipitation"},
                            {"name": "daily", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Comma-separated daily variables, e.g. temperature_2m_max,temperature_2m_min"},
                        ]
                    }
                }
            }
        }
    },
    {
        "id": "coingecko",
        "name": "CoinGecko Crypto",
        "category": "Finance & Web3",
        "kind": "openapi",
        "description": "Live cryptocurrency prices, market caps, 24h volume, and market trends across thousands of tokens.",
        "icon": "🪙",
        "author": "CoinGecko",
        "homepage": "https://coingecko.com",
        "base_url": "https://api.coingecko.com/api/v3",
        "auth_type": "none",
        "spec_raw": {
            "openapi": "3.0.0",
            "info": {"title": "CoinGecko V3 Public API", "version": "3.0.0"},
            "servers": [{"url": "https://api.coingecko.com/api/v3"}],
            "paths": {
                "/simple/price": {
                    "get": {
                        "operationId": "get_crypto_price",
                        "summary": "Get current price of cryptocurrencies in USD/EUR/etc.",
                        "parameters": [
                            {"name": "ids", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Comma-separated crypto IDs, e.g. bitcoin,ethereum,solana"},
                            {"name": "vs_currencies", "in": "query", "required": True, "schema": {"type": "string"}, "description": "Target currency, e.g. usd,eur,inr"},
                            {"name": "include_24hr_change", "in": "query", "required": False, "schema": {"type": "boolean"}, "description": "Include 24h price change percentage"}
                        ]
                    }
                },
                "/search/trending": {
                    "get": {
                        "operationId": "get_trending_coins",
                        "summary": "Get top 7 trending coins searched by users in the last 24 hours"
                    }
                }
            }
        }
    },
    {
        "id": "hackernews",
        "name": "HackerNews Reader",
        "category": "Tech & News",
        "kind": "openapi",
        "description": "Official Firebase HackerNews API for top stories, new items, and developer discussions.",
        "icon": "📰",
        "author": "Y Combinator",
        "homepage": "https://news.ycombinator.com",
        "base_url": "https://hacker-news.firebaseio.com/v0",
        "auth_type": "none",
        "spec_raw": {
            "openapi": "3.0.0",
            "info": {"title": "HackerNews API", "version": "v0"},
            "servers": [{"url": "https://hacker-news.firebaseio.com/v0"}],
            "paths": {
                "/topstories.json": {
                    "get": {
                        "operationId": "get_top_stories",
                        "summary": "Returns up to 500 top story IDs on Hacker News"
                    }
                },
                "/item/{id}.json": {
                    "get": {
                        "operationId": "get_item_details",
                        "summary": "Get details of a story, comment, or job by ID",
                        "parameters": [
                            {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "The item's unique ID"}
                        ]
                    }
                }
            }
        }
    },
    {
        "id": "github_mcp",
        "name": "GitHub MCP Server",
        "category": "Developer Tools",
        "kind": "mcp_stdio",
        "description": "Model Context Protocol server for inspecting repositories, issues, commits, and pull requests.",
        "icon": "🐙",
        "author": "Model Context Protocol",
        "homepage": "https://github.com/modelcontextprotocol/servers",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "auth_type": "api_key",
        "auth_hint": "Set GITHUB_PERSONAL_ACCESS_TOKEN in env",
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": ""}
    },
    {
        "id": "sqlite_mcp",
        "name": "SQLite MCP Explorer",
        "category": "Databases",
        "kind": "mcp_stdio",
        "description": "Directly execute read-only queries and inspect schema on local SQLite database files.",
        "icon": "🗄️",
        "author": "Model Context Protocol",
        "homepage": "https://github.com/modelcontextprotocol/servers",
        "command": "uvx",
        "args": ["mcp-server-sqlite", "--db-path", "data/makima.db"],
        "auth_type": "none"
    },
    {
        "id": "fetch_mcp",
        "name": "Web Fetch & Markdown MCP",
        "category": "Web & Search",
        "kind": "mcp_stdio",
        "description": "Fetches web pages and efficiently converts HTML to clean markdown for the AI model.",
        "icon": "🌐",
        "author": "Model Context Protocol",
        "homepage": "https://github.com/modelcontextprotocol/servers",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "auth_type": "none"
    }
]


def get_marketplace_catalog() -> List[Dict[str, Any]]:
    return list(MARKETPLACE_CATALOG)


async def fetch_external_catalog(url_or_path: str, timeout_s: float = 12.0) -> List[Dict[str, Any]]:
    """Fetches and normalizes a plugin marketplace catalog from an external URL or custom registry feed."""
    import json
    import os
    import re
    from pathlib import Path
    import httpx

    target = url_or_path.strip()
    data = None

    if target.startswith("http://") or target.startswith("https://"):
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            resp = await client.get(target, headers={"User-Agent": "Makima/2.0 Extensibility Hub"})
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").lower()
            text = resp.text.strip()
            if "text/html" in content_type or text.startswith("<!DOCTYPE") or text.startswith("<html"):
                raise ValueError(
                    f"'{target}' returned an HTML webpage instead of a JSON registry feed. "
                    "Make sure the URL points to a raw JSON API endpoint or catalog feed."
                )
            data = resp.json()
    elif target.startswith("file://") or os.path.exists(target):
        file_path = target.replace("file:///", "").replace("file://", "")
        p = Path(file_path)
        if not p.is_file():
            raise FileNotFoundError(f"Registry file not found at '{target}'")
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Invalid registry URL or path: '{target}'. Must start with http://, https://, or be a valid file path.")

    # Extract items collection
    raw_items: List[Any] = []
    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict):
        if "catalog" in data and isinstance(data["catalog"], list):
            raw_items = data["catalog"]
        elif "plugins" in data and isinstance(data["plugins"], list):
            raw_items = data["plugins"]
        elif "servers" in data and isinstance(data["servers"], list):
            raw_items = data["servers"]
        elif "items" in data and isinstance(data["items"], list):
            raw_items = data["items"]
        elif "extensions" in data and isinstance(data["extensions"], list):
            raw_items = data["extensions"]
        else:
            raw_items = [data]

    seen_ids = set()
    normalized: List[Dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        # Unpack Official MCP Registry wrappers {"server": {...}, "_meta": ...}
        if "server" in raw and isinstance(raw["server"], dict):
            raw = {**raw, **raw["server"]}

        item_id = str(raw.get("id") or raw.get("name") or raw.get("qualifiedName") or "ext").lower()
        item_id = re.sub(r"[^a-z0-9_]+", "_", item_id).strip("_")

        # Deduplicate IDs
        unique_id = item_id
        counter = 1
        while unique_id in seen_ids:
            counter += 1
            unique_id = f"{item_id}_{counter}"
        seen_ids.add(unique_id)

        name = str(raw.get("title") or raw.get("name") or raw.get("displayName") or raw.get("qualifiedName") or unique_id)
        category = str(raw.get("category") or "Community")
        kind = str(raw.get("kind") or ("mcp_stdio" if ("command" in raw or "args" in raw or "mcp" in name.lower()) else "openapi"))
        description = str(raw.get("description") or "Community extension plugin")
        author = str(raw.get("author") or raw.get("vendor") or "Community")
        homepage_raw = raw.get("homepage") or raw.get("repository") or raw.get("url")
        homepage = None
        if isinstance(homepage_raw, str):
            homepage = homepage_raw
        elif isinstance(homepage_raw, dict):
            homepage = homepage_raw.get("url") or homepage_raw.get("link")
        elif isinstance(homepage_raw, list) and homepage_raw:
            homepage = str(homepage_raw[0])

        base_url_raw = raw.get("base_url")
        base_url = str(base_url_raw) if isinstance(base_url_raw, str) else None

        # Handle MCP remotes (streamable-http / sse)
        if "remotes" in raw and isinstance(raw["remotes"], list) and raw["remotes"]:
            remote = raw["remotes"][0]
            if isinstance(remote, dict) and "url" in remote:
                base_url = str(remote["url"])
                homepage = homepage or str(remote["url"])

        if homepage is not None:
            homepage = str(homepage)
        if base_url is not None:
            base_url = str(base_url)

        # Smart Icon / Logo Resolution
        icon_cand = raw.get("icon") or raw.get("logo") or raw.get("icon_url") or raw.get("avatar_url") or raw.get("image")
        icon = None
        if isinstance(icon_cand, str) and icon_cand.strip():
            icon = icon_cand.strip()
        elif isinstance(icon_cand, dict) and "url" in icon_cand:
            icon = str(icon_cand["url"]).strip()

        # If no explicit icon, resolve from GitHub or domain
        if not icon and homepage:
            gh_match = re.search(r"github\.com/([^/]+)", homepage, re.IGNORECASE)
            if gh_match and gh_match.group(1).lower() not in ("modelcontextprotocol", "features", "marketplace"):
                icon = f"https://github.com/{gh_match.group(1)}.png"
            else:
                domain_match = re.search(r"https?://([^/:]+)", homepage)
                if domain_match:
                    d = domain_match.group(1)
                    if d not in ("localhost", "127.0.0.1"):
                        icon = f"https://www.google.com/s2/favicons?domain={d}&sz=64"

        if not icon and base_url:
            domain_match = re.search(r"https?://([^/:]+)", base_url)
            if domain_match:
                d = domain_match.group(1)
                if d not in ("localhost", "127.0.0.1"):
                    icon = f"https://www.google.com/s2/favicons?domain={d}&sz=64"

        if not icon:
            low = f"{name} {category} {description}".lower()
            if any(k in low for k in ["github", "git"]):
                icon = "🐙"
            elif any(k in low for k in ["sql", "postgres", "database", "db"]):
                icon = "🗄️"
            elif any(k in low for k in ["weather", "climate", "forecast", "meteo"]):
                icon = "🌤️"
            elif any(k in low for k in ["crypto", "coin", "token", "bitcoin", "eth"]):
                icon = "🪙"
            elif any(k in low for k in ["news", "hackernews", "article", "feed"]):
                icon = "📰"
            elif any(k in low for k in ["voice", "speech", "audio", "sound", "tts"]):
                icon = "🎙️"
            elif any(k in low for k in ["search", "brave", "google", "web"]):
                icon = "🔍"
            elif any(k in low for k in ["slack", "chat", "message", "discord"]):
                icon = "💬"
            elif any(k in low for k in ["docker", "container", "devops"]):
                icon = "🐳"
            elif any(k in low for k in ["ai", "model", "inference", "llm", "gpt"]):
                icon = "🤖"
            elif any(k in low for k in ["finance", "price", "lead", "tax"]):
                icon = "📈"
            elif any(k in low for k in ["plant", "garden"]):
                icon = "🌱"
            elif any(k in low for k in ["estate", "house", "property"]):
                icon = "🏢"
            else:
                icon = "🧩"

        auth_type = str(raw.get("auth_type") or ("api_key" if (raw.get("env") or raw.get("token")) else "none"))

        entry: Dict[str, Any] = {
            "id": unique_id,
            "name": name,
            "category": category,
            "kind": kind,
            "description": description,
            "icon": icon,
            "author": author,
            "homepage": homepage,
            "auth_type": auth_type,
            "auth_hint": str(raw["auth_hint"]) if raw.get("auth_hint") else None,
            "base_url": base_url,
            "spec_url": str(raw["spec_url"]) if raw.get("spec_url") else None,
            "spec_raw": raw.get("spec_raw") if isinstance(raw.get("spec_raw"), dict) else None,
            "command": str(raw["command"]) if raw.get("command") else None,
            "args": [str(a) for a in raw.get("args")] if isinstance(raw.get("args"), list) else [],
            "env": {str(k): str(v) for k, v in raw.get("env").items()} if isinstance(raw.get("env"), dict) else {},
        }
        normalized.append(entry)

    return normalized

