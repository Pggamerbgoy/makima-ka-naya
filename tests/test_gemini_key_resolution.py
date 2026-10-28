import os
import pytest
from makima.config import BackendConfig
from makima.provider.adapters.gemini import GeminiProvider
from makima.voice.gemini_live import GeminiLiveSession


def test_backend_config_gemini_key_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key-12345")

    cfg = BackendConfig(adapter="gemini", model="gemini-2.5-flash", api_key_env="GEMINI_API_KEY")
    assert cfg.api_key == "test-google-key-12345"
    assert cfg.is_available is True


def test_backend_config_direct_gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key-99999")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key-12345")

    cfg = BackendConfig(adapter="gemini", model="gemini-2.5-flash", api_key_env="GEMINI_API_KEY")
    assert cfg.api_key == "test-gemini-key-99999"
    assert cfg.is_available is True


def test_gemini_provider_client_key_detection(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-fallback-key")

    cfg = BackendConfig(adapter="gemini", model="gemini-2.5-flash", api_key_env="GEMINI_API_KEY")
    provider = GeminiProvider(config=cfg)
    client = provider._get_client()
    assert client is not None


def test_voice_client_key_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-voice-fallback-key")

    voice = GeminiLiveSession()
    assert voice.api_key == "test-voice-fallback-key"
    client = voice._get_client()
    assert client is not None


def test_gemini_tool_schema_sanitization_extra_forbidden():
    """Verifies that MCP/JSON Schema tools with $schema, $id, or draft-07 types don't trip Pydantic extra_forbidden."""
    from makima.provider.adapters.gemini import _sanitize_gemini_schema
    from google.genai import types

    raw_tool_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "https://example.com/tool86.json",
        "type": "object",
        "properties": {
            "query": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": ["string", "null"],
                "description": "User search query",
                "custom_metadata_tag": "should_be_stripped",
            },
            "limit": {
                "type": "integer",
                "$comment": "maximum results",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    sanitized = _sanitize_gemini_schema(raw_tool_schema)
    assert "$schema" not in sanitized
    assert "$id" not in sanitized
    assert "query" in sanitized["properties"]
    assert sanitized["properties"]["query"]["nullable"] is True
    assert sanitized["properties"]["query"]["type"] == "string"

    # Instantiate Gemini FunctionDeclaration to verify Pydantic accepts it without extra_forbidden
    decl = types.FunctionDeclaration(
        name="tool_86_test",
        description="Search tool",
        parameters=sanitized,
    )
    assert decl.name == "tool_86_test"


def test_gemini_provider_convert_tools_with_mcp_schemas():
    """Verifies that GeminiProvider._convert_tools seamlessly handles MCP tool schemas with $schema."""
    cfg = BackendConfig(adapter="gemini", model="gemini-2.5-flash", api_key_env="GEMINI_API_KEY")
    provider = GeminiProvider(config=cfg)

    mcp_tools = [
        {
            "type": "function",
            "function": {
                "name": "mcp_filesystem_read_file",
                "description": "Read file contents",
                "parameters": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "object",
                    "properties": {
                        "path": {
                            "$schema": "nested",
                            "type": "string",
                            "description": "Absolute path",
                        }
                    },
                    "required": ["path"],
                },
            },
        }
    ]

    converted = provider._convert_tools(mcp_tools)
    assert converted is not None
    assert len(converted) == 1
    decls = converted[0].function_declarations
    assert len(decls) == 1
    assert decls[0].name == "mcp_filesystem_read_file"

