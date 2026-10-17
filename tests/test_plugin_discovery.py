"""Tests for ChatGPT Plugin & OpenAPI Auto-Discovery Service."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
import pytest
import httpx

from makima.plugins.discovery import discover_plugin_or_api


@pytest.mark.asyncio
async def test_discover_chatgpt_plugin_manifest() -> None:
    manifest_payload = {
        "schema_version": "v1",
        "name_for_human": "Crypto Tracker",
        "name_for_model": "crypto_tracker",
        "description_for_human": "Track live crypto prices and trends.",
        "description_for_model": "Track crypto prices.",
        "auth": {"type": "user_http"},
        "api": {
            "type": "openapi",
            "url": "https://crypto.example.com/api/openapi.json",
        },
        "logo_url": "https://crypto.example.com/logo.png",
    }
    openapi_payload = {
        "openapi": "3.0.0",
        "info": {"title": "Crypto API", "version": "1.0.0"},
        "servers": [{"url": "https://crypto.example.com/api"}],
        "paths": {
            "/prices": {
                "get": {
                    "operationId": "get_prices",
                    "summary": "Fetch current prices",
                    "parameters": [{"name": "coin", "in": "query", "schema": {"type": "string"}}],
                }
            }
        },
    }

    async def mock_get(self, url, *args, **kwargs):
        url_str = str(url)
        if "/.well-known/ai-plugin.json" in url_str:
            return httpx.Response(200, json=manifest_payload, request=httpx.Request("GET", url_str))
        elif "/api/openapi.json" in url_str:
            return httpx.Response(200, json=openapi_payload, request=httpx.Request("GET", url_str))
        return httpx.Response(404, request=httpx.Request("GET", url_str))

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        res = await discover_plugin_or_api("https://crypto.example.com")
        assert res.ok is True
        assert res.plugin_type == "chatgpt_plugin"
        assert res.name == "Crypto Tracker"
        assert res.auth_type == "bearer"
        assert len(res.endpoints) == 1
        assert res.endpoints[0].operation_id == "get_prices"


@pytest.mark.asyncio
async def test_discover_direct_openapi_spec() -> None:
    openapi_payload = {
        "openapi": "3.0.0",
        "info": {"title": "Petstore API", "version": "1.0.0"},
        "servers": [{"url": "https://petstore.example.com/v1"}],
        "paths": {
            "/pets": {
                "get": {
                    "operationId": "list_pets",
                    "summary": "List all pets",
                }
            }
        },
    }

    async def mock_get(self, url, *args, **kwargs):
        url_str = str(url)
        if "/.well-known/ai-plugin.json" in url_str:
            return httpx.Response(404, request=httpx.Request("GET", url_str))
        elif "/openapi.json" in url_str:
            return httpx.Response(200, json=openapi_payload, request=httpx.Request("GET", url_str))
        return httpx.Response(404, request=httpx.Request("GET", url_str))

    with patch.object(httpx.AsyncClient, "get", new=mock_get):
        res = await discover_plugin_or_api("https://petstore.example.com")
        assert res.ok is True
        assert res.plugin_type == "openapi"
        assert res.name == "Petstore API"
        assert len(res.endpoints) == 1
        assert res.endpoints[0].operation_id == "list_pets"
