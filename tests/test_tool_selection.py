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
