from __future__ import annotations

import asyncio
from types import ModuleType, SimpleNamespace
from typing import Any, Iterable, List

import pytest

from makima.core.engine import HermesAgentEngine
from makima.provider.adapters.base import ProviderResponse, ToolCall
from makima.tools.registry import Tool, ToolRegistry
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



class QueueRouter:
    """Small deterministic router for exercising engine wiring without a provider."""

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get_ranked_candidates(self, _task: str = "fast_chat") -> list[Any]:
        return []

    async def execute_with_fallback(self, **kwargs: Any) -> ProviderResponse:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("Unexpected provider call: response queue is empty")
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_plain_text_tool_trace_is_never_executed() -> None:
    router = QueueRouter([
        ProviderResponse(
            content=(
                "I'll check that now.\\n"
                "[Executed Tools in Turn: browser_interact(action='navigate', url='https://example.com') -> ok]"
            ),
            tool_calls=[],
            finish_reason="stop",
            model="mock",
        )
    ])
    engine = HermesAgentEngine(router=router, enable_implicit_learning=False)
    executed: list[tuple[str, dict[str, Any]]] = []

    async def executor(name: str, args: dict[str, Any]) -> dict[str, bool]:
        executed.append((name, args))
        return {"success": True}

    result = await engine.run(
        prompt="Open example.com",
        tools=[schema("browser_interact", "Navigate a browser to a URL.")],
        tool_executor=executor,
    )

    assert executed == []
    assert result.tool_calls_executed == 0
    assert "[Executed Tools in Turn:" not in result.content
    assert "No action was executed" in result.content


@pytest.mark.asyncio
async def test_no_tools_exposed_means_structured_tool_calls_are_blocked() -> None:
    router = QueueRouter([
        ProviderResponse(
            content="",
            tool_calls=[ToolCall(id="call-1", name="unexposed_action", arguments={})],
            finish_reason="tool_calls",
            model="mock",
        ),
        ProviderResponse(content="No action was run.", finish_reason="stop", model="mock"),
    ])
    engine = HermesAgentEngine(router=router, enable_implicit_learning=False)
    executed: list[str] = []

    async def executor(name: str, _args: dict[str, Any]) -> dict[str, bool]:
        executed.append(name)
        return {"success": True}

    result = await engine.run(
        prompt="Do something",
        tools=None,
        tool_executor=executor,
    )

    assert executed == []
    assert "[TOOL_NOT_AVAILABLE: unexposed_action]" in "\\n".join(
        message.content or "" for message in result.messages if message.role == "tool"
    )


@pytest.mark.asyncio
async def test_semantic_selector_miss_expands_full_catalog_on_next_turn() -> None:
    names = ["a_weather"] + [f"mid_tool_{i:02d}" for i in range(34)] + ["z_set_volume"]
    schemas = [schema(name, f"Tool named {name}.") for name in names]

    class NarrowSelector:
        def __init__(self) -> None:
            self.calls = 0

        async def select_schemas(self, available: list[dict[str, Any]], query: str, *, tool_metadata: Any = None) -> list[dict[str, Any]]:
            self.calls += 1
            return [next(item for item in available if item["function"]["name"] == "a_weather")]

    selector = NarrowSelector()
    router = QueueRouter([
        ProviderResponse(
            content="",
            tool_calls=[ToolCall(id="hidden-1", name="z_set_volume", arguments={"volume": 40})],
            finish_reason="tool_calls",
            model="mock",
        ),
        ProviderResponse(
            content="",
            tool_calls=[ToolCall(id="visible-2", name="z_set_volume", arguments={"volume": 40})],
            finish_reason="tool_calls",
            model="mock",
        ),
        ProviderResponse(content="Volume set to 40.", finish_reason="stop", model="mock"),
    ])
    engine = HermesAgentEngine(
        router=router,
        tool_selector=selector,
        enable_implicit_learning=False,
        max_turns=5,
    )
    executed: list[tuple[str, dict[str, Any]]] = []

    async def executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
        executed.append((name, args))
        return {"success": True, "volume": args["volume"]}

    result = await engine.run(
        prompt="Set volume to 40",
        tools=schemas,
        tool_executor=executor,
    )

    assert selector.calls == 2, "Normal turns use semantic retrieval; the recovery turn alone must expose the full catalogue."
    assert "z_set_volume" not in {
        item["function"]["name"] for item in router.calls[0]["tools"]
    }
    assert "z_set_volume" in {
        item["function"]["name"] for item in router.calls[1]["tools"]
    }
    assert executed == [("z_set_volume", {"volume": 40})]
    assert result.completed is True


@pytest.mark.asyncio
async def test_custom_schema_set_does_not_borrow_parallel_safety_from_global_registry() -> None:
    from makima.tools.registry import get_registry

    unique_a = "parallel_probe_a_82f1"
    unique_b = "parallel_probe_b_82f1"

    async def global_read() -> dict[str, bool]:
        return {"ok": True}

    reg = get_registry()
    reg.register(global_read, name=unique_a, parallel_safe=True)
    reg.register(global_read, name=unique_b, parallel_safe=True)

    active = 0
    max_active = 0

    async def custom_executor(name: str, _args: dict[str, Any]) -> dict[str, bool]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return {"tool": name}

    router = QueueRouter([
        ProviderResponse(
            content="",
            tool_calls=[
                ToolCall(id="parallel-a", name=unique_a, arguments={}),
                ToolCall(id="parallel-b", name=unique_b, arguments={}),
            ],
            finish_reason="tool_calls",
            model="mock",
        ),
        ProviderResponse(content="Done.", finish_reason="stop", model="mock"),
    ])
    engine = HermesAgentEngine(router=router, enable_implicit_learning=False)
    await engine.run(
        prompt="Run the two custom actions",
        tools=[schema(unique_a, "Custom action A."), schema(unique_b, "Custom action B.")],
        tool_executor=custom_executor,
    )

    assert max_active == 1, "A raw schema list has no safety metadata; calls must be serialized."



@pytest.mark.asyncio
async def test_gemini_live_uses_injected_gateway_for_voice_tool_execution(monkeypatch: Any) -> None:
    from makima.voice import gemini_live

    registry = ToolRegistry(name="voice-gateway-test")
    executions: list[str] = []

    async def dangerous_action(target: str) -> dict[str, bool]:
        executions.append(target)
        return {"success": True}

    registry.register(
        dangerous_action,
        name="voice_test_action",
        description="Test-only side effect.",
        tags=["control"],
    )
    disabled = {"voice_test_action"}
    gateway = ToolExecutionGateway(registry, lambda: disabled)

    class FakeLiveSocket:
        def __init__(self) -> None:
            self.sent: list[Any] = []

        async def receive(self):
            yield SimpleNamespace(
                server_content=None,
                tool_call=SimpleNamespace(
                    function_calls=[
                        SimpleNamespace(
                            name="voice_test_action",
                            args={"target": "must-not-run"},
                            id="voice-call-1",
                        )
                    ]
                ),
            )

        async def send(self, *, input: Any) -> None:
            self.sent.append(input)

    class FakeFunctionResponse:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class FakeToolResponse:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(gemini_live.types, "FunctionResponse", FakeFunctionResponse)
    monkeypatch.setattr(gemini_live.types, "LiveClientToolResponse", FakeToolResponse)

    session = gemini_live.GeminiLiveSession(execution_gateway=gateway)
    session._session = FakeLiveSocket()
    session._is_active = True
    session._available_tool_names = {"voice_test_action"}

    events = [event async for event in session.receive_events()]

    assert executions == [], "Disabled voice tools must not run through a direct registry bypass."
    tool_result = next(event for event in events if event["type"] == "tool_result")
    assert "[TOOL_DISABLED: voice_test_action]" in str(tool_result["result"])
    assert session._session.sent, "The gateway result must be returned to Gemini as a function response."



@pytest.mark.asyncio
async def test_explicit_registry_reload_replaces_stale_tool_implementation() -> None:
    registry = ToolRegistry(name="reload-test")

    def old_implementation() -> str:
        return "old"

    registry.register(old_implementation, name="reloadable_action")
    module = ModuleType("test_dynamic_plugin_module")

    def new_implementation() -> str:
        return "new"

    new_tool = Tool.from_function(new_implementation, name="reloadable_action")
    setattr(new_implementation, "__makima_tool__", True)
    setattr(new_implementation, "__tool_obj__", new_tool)
    setattr(module, "reloadable_action", new_implementation)

    registry.discover(package=module, reload=True)

    assert registry["reloadable_action"].fn is new_implementation
    assert await registry.execute("reloadable_action", {}) == "new"



@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "limit"),
    [(False, 8), (True, 1)],
)
async def test_configured_tool_concurrency_is_honored(
    monkeypatch: Any,
    enabled: bool,
    limit: int,
) -> None:
    import makima.config as config_module

    selection = SimpleNamespace(
        enabled=False,
        embedding_model="test",
        max_candidates=96,
        minimum_candidates=24,
        minimum_similarity=0.2,
    )
    concurrency = SimpleNamespace(
        enabled=enabled,
        max_concurrency=limit,
        parallel_safe_tags=["search"],
        mutating_tags=["write"],
    )
    fake_settings = SimpleNamespace(
        tools=SimpleNamespace(selection=selection, concurrency=concurrency),
        tool_timeout=2.0,
        max_tool_output_chars=16000,
    )
    monkeypatch.setattr(config_module, "get_settings", lambda: fake_settings)

    registry = ToolRegistry(name=f"concurrency-{enabled}-{limit}")
    active = 0
    max_active = 0

    async def harmless_read() -> dict[str, bool]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return {"ok": True}

    first_name = f"concurrency_tool_a_{enabled}_{limit}"
    second_name = f"concurrency_tool_b_{enabled}_{limit}"
    registry.register(harmless_read, name=first_name, parallel_safe=True, tags=["search"])
    registry.register(harmless_read, name=second_name, parallel_safe=True, tags=["search"])

    router = QueueRouter([
        ProviderResponse(
            content="",
            tool_calls=[
                ToolCall(id="parallel-a", name=first_name, arguments={}),
                ToolCall(id="parallel-b", name=second_name, arguments={}),
            ],
            finish_reason="tool_calls",
            model="mock",
        ),
        ProviderResponse(content="Done.", finish_reason="stop", model="mock"),
    ])
    engine = HermesAgentEngine(
        router=router,
        tool_selector=ToolSelectionService(selection, embedding_factory=lambda _model: DirectionalEmbedding()),
        enable_implicit_learning=False,
    )

    result = await engine.run(prompt="Check both harmless states", tools=registry)

    assert result.completed is True
    assert max_active <= limit if enabled else max_active == 1



def test_gemini_live_is_reserved_for_voice_routing() -> None:
    from makima.config import get_settings

    settings = get_settings()
    for task_name in ("fast_chat", "code", "deep_reasoning", "vision"):
        assert "gemini_live" not in settings.providers.cascades[task_name]
        assert "gemini_3_8_live" not in settings.providers.cascades[task_name]

    assert settings.providers.cascades["voice"] == ["gemini_live"]
    assert "gemini_3_8_live" not in settings.providers.backends



@pytest.mark.asyncio
async def test_fallback_tool_schema_is_hidden_only_when_primary_is_available() -> None:
    registry = ToolRegistry(name="fallback-selection-test")

    def primary_lookup(query: str) -> dict[str, str]:
        return {"source": "primary", "query": query}

    def fallback_lookup(query: str) -> dict[str, str]:
        return {"source": "fallback", "query": query}

    registry.register(primary_lookup, name="primary_lookup", tags=["search"])
    registry.register(
        fallback_lookup,
        name="fallback_lookup",
        tags=["search"],
        fallback_for="primary_lookup",
    )

    schemas = registry.get_schemas()
    assert [item["function"]["name"] for item in schemas] == ["primary_lookup"]
    assert await registry.execute("fallback_lookup", {"query": "still callable"}) == {
        "source": "fallback",
        "query": "still callable",
    }

    disabled_primary_gateway = ToolExecutionGateway(
        registry,
        disabled_tools={"primary_lookup"},
    )
    fallback_schemas = disabled_primary_gateway.get_schemas()
    assert [item["function"]["name"] for item in fallback_schemas] == ["fallback_lookup"]
