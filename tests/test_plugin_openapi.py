"""Tests for OpenAPI Action Adapter in Makima Extensibility Hub."""

from __future__ import annotations

from unittest.mock import patch
import pytest
import httpx

from makima.plugins.manifest import PluginManifest
from makima.plugins.openapi_client import OpenAPIClient
from makima.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_openapi_client_tool_registration_and_execution() -> None:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Weather Service", "version": "1.0.0"},
        "servers": [{"url": "https://api.weather-mock.com"}],
        "paths": {
            "/current": {
                "get": {
                    "operationId": "get_current_weather",
                    "summary": "Get current weather by city",
                    "parameters": [
                        {"name": "city", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                }
            }
        },
    }

    manifest = PluginManifest(
        name="weather",
        kind="openapi",
        enabled=True,
        trusted=True,
        spec_raw=spec,
        base_url="https://api.weather-mock.com",
        auth_type="bearer",
        auth_config={"token": "test-secret-key-123"},
    )

    registry = ToolRegistry()
    client = OpenAPIClient(manifest)

    tools = await client.load_tools(registry)
    assert len(tools) == 1
    assert "weather_get_current_weather" in tools
    assert "weather_get_current_weather" in registry.list_names()

    # Mock the HTTP call
    captured_request = []

    async def mock_request(self, method, url, *args, **kwargs):
        captured_request.append({"method": method, "url": str(url), "kwargs": kwargs})
        return httpx.Response(
            200,
            json={"city": "Tokyo", "temperature": 22.5, "condition": "Sunny"},
            request=httpx.Request(method, url),
        )

    with patch.object(httpx.AsyncClient, "request", new=mock_request):
        tool = registry.get("weather_get_current_weather")
        assert tool is not None
        result_str = await tool.fn(city="Tokyo")
        assert len(captured_request) == 1
        req = captured_request[0]
        assert req["kwargs"]["headers"]["Authorization"] == "Bearer test-secret-key-123"
        assert req["kwargs"]["params"]["city"] == "Tokyo"
        assert "Tokyo" in result_str
        assert "Sunny" in result_str

    await client.close()
