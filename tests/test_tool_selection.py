from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable, List

import pytest

from makima.core.engine import HermesAgentEngine
from makima.provider.adapters.base import ToolCall
from makima.tools.registry import ToolRegistry
from makima.tools.selection import ToolExecutionGateway, ToolSelectionService


class DirectionalEmbedding:
    """Deterministic embedding fixture for testing ranking without model downloads."""

    def embed(self, texts: Iterable[str]) -> List[List[float]]:
        vectors = []
        for text in texts:
            if text.startswith("User request and current task context:"):
                vectors.append([1.0, 0.0])
            elif "Tool name: close_application" in text:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors


class UnrelatedEmbedding:
    """Embeddings that intentionally make every catalogue entry irrelevant."""

    def embed(self, texts: Iterable[str]) -> List[List[float]]:
        vectors = []
        for text in texts:
            if text.startswith("User request and current task context:"):
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors


def schema(name: str, description: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }


@pytest.mark.asyncio
async def test_semantic_selector_retrieves_by_tool_description_not_request_keywords() -> None:
    selector = ToolSelectionService(
        SimpleNamespace(
            enabled=True,
            embedding_model="test",
            max_candidates=1,
            minimum_candidates=1,
            minimum_similarity=0.5,
        ),
        embedding_factory=lambda _model: DirectionalEmbedding(),
    )
    schemas = [
        schema("close_application", "Close an identified desktop application."),
        schema("control_media", "Control active media playback."),
    ]

    selected = await selector.select_schemas(
        schemas,
        "Keep the audio running and close the requested desktop program.",
    )

    assert selected is not None
    assert [item["function"]["name"] for item in selected] == ["close_application"]


@pytest.mark.asyncio
async def test_semantic_selector_fails_open_when_relevance_is_uncertain() -> None:
    selector = ToolSelectionService(
        SimpleNamespace(
            enabled=True,
            embedding_model="test",
            max_candidates=1,
            minimum_candidates=1,
            minimum_similarity=0.9,
        ),
        embedding_factory=lambda _model: UnrelatedEmbedding(),
    )
    schemas = [
        schema("close_application", "Close an identified desktop application."),
        schema("control_media", "Control active media playback."),
    ]

    selected = await selector.select_schemas(schemas, "Handle this task.")

    assert selected == schemas


@pytest.mark.asyncio
async def test_execution_gateway_enforces_enabled_state_and_per_turn_allowlist() -> None:
    registry = ToolRegistry(name="selection-test")
    calls: list[str] = []

    async def close_application(app_name: str) -> dict[str, Any]:
        calls.append(app_name)
        return {"success": True, "app_name": app_name}

    registry.register(
        close_application,
        name="close_application",
        description="Close a running desktop application.",
        tags=["apps", "control"],
    )

    disabled: set[str] = set()
    gateway = ToolExecutionGateway(registry, lambda: disabled)

    not_exposed = await gateway.execute(
        "close_application",
        {"app_name": "Claude"},
        allowed_tool_names={"control_media"},
    )
    assert "[TOOL_NOT_AVAILABLE" in not_exposed
    assert calls == []

    disabled.add("close_application")
    blocked = await gateway.execute("close_application", {"app_name": "Claude"})
    assert "[TOOL_DISABLED" in blocked
    assert calls == []

    disabled.clear()
    result = await gateway.execute(
        "close_application",
        {"app_name": "Claude"},
        allowed_tool_names={"close_application"},
    )
    assert result == {"success": True, "app_name": "Claude"}
    assert calls == ["Claude"]


@pytest.mark.asyncio
async def test_structured_tool_metadata_is_included_in_model_schema() -> None:
    registry = ToolRegistry(name="metadata-test")

    async def close_application(app_name: str) -> dict[str, Any]:
        return {"success": True, "app_name": app_name}

    tool = registry.register(
        close_application,
        name="close_application",
        description="Close a running desktop application.",
        tags=["apps", "control"],
        purpose="Close a named application without changing media playback.",
        capabilities=["Close a target application by name."],
        use_when=["The target is a running desktop application."],
        avoid_when=["The user asks only to pause or stop media playback."],
        examples=["Close a desktop application while leaving music playing."],
        side_effect="Requests application closure.",
    )

    description = tool.to_schema()["function"]["description"]

    assert "Purpose:" in description
    assert "Capabilities:" in description
    assert "Use when:" in description
    assert "Do not use when:" in description
    assert "Examples:" in description
    assert "Side effects:" in description


@pytest.mark.asyncio
async def test_gateway_applies_command_guardrails_for_every_interface() -> None:
    registry = ToolRegistry(name="guardrail-test")

    async def execute_command(command: str) -> dict[str, Any]:
        return {"success": True, "command": command}

    registry.register(
        execute_command,
        name="execute_command",
        description="Execute a shell command.",
        tags=["terminal", "execution"],
    )
    gateway = ToolExecutionGateway(registry)

    result = await gateway.execute(
        "execute_command",
        {"command": "format C:"},
        allowed_tool_names={"execute_command"},
    )

    assert "[GUARDRAIL_BLOCKED: execute_command]" in result


def test_selection_context_keeps_user_corrections_and_observed_tool_results() -> None:
    from makima.provider.adapters.base import Message

    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="old-call",
                    name="control_media",
                    arguments={"action": "stop"},
                )
            ],
        ),
        Message(
            role="tool",
            name="control_media",
            content='{"success": true, "action": "stop", "source_app": "Claude"}',
        ),
        Message(role="user", content="Keep the music playing and close the app."),
    ]

    context = HermesAgentEngine._tool_selection_context(
        "Keep the music playing and close the app.",
        messages,
    )

    assert '"tool": "control_media"' in context
    assert '"action": "stop"' in context
    assert "Recent observed result (control_media)" in context
    assert "Keep the music playing" in context


@pytest.mark.asyncio
async def test_engine_never_executes_a_tool_absent_from_current_schemas() -> None:
    engine = HermesAgentEngine(router=object(), enable_implicit_learning=False)
    called: list[str] = []

    async def executor(name: str, _arguments: dict[str, Any]) -> dict[str, bool]:
        called.append(name)
        return {"success": True}

    result = await engine._execute_tool_call(
        ToolCall(id="test-call", name="close_application", arguments={"app_name": "Claude"}),
        executor,
        allowed_tool_names=set(),
    )

    assert result.startswith("[TOOL_NOT_AVAILABLE")
    assert called == []
