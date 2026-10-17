"""Contract tests preventing OSWorld runs from being misattributed."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from benchmarks.osworld_makima import MakimaOSWorldAgent, OSWORLD_SYSTEM_PROMPT
from benchmarks.run_osworld_makima import _official_osworld_runtime_available
from makima.core.engine import HermesAgentEngine
from makima.config import get_settings
from makima.provider.adapters.base import BaseProvider, Message, ProviderResponse, ToolCall
from makima.provider.router import ParetoCandidate, ParetoRouter
from makima.tools.registry import ToolRegistry


class _Provider(BaseProvider):
    def __init__(self) -> None:
        config = MagicMock()
        config.model = "qwen3-alibaba-backend"
        config.is_available = True
        super().__init__(config=config)
        self.responses = [
            ProviderResponse(
                model=self.name,
                tool_calls=[ToolCall(id="call-1", name="record_action", arguments={"value": "clicked"})],
            ),
            ProviderResponse(model=self.name, content="Makima completed the task."),
        ]
        self.system_prompts: List[str] = []

    async def generate(self, messages: List[Message], tools=None, system_prompt=None, **kwargs) -> ProviderResponse:
        self.system_prompts.append(system_prompt or "")
        return self.responses.pop(0)

    async def stream(self, *args, **kwargs):
        raise NotImplementedError


class _Router(ParetoRouter):
    def __init__(self, provider: _Provider) -> None:
        super().__init__()
        self._providers["backend"] = provider

    def get_ranked_candidates(self, task: str = "fast_chat") -> List[ParetoCandidate]:
        return [ParetoCandidate("backend", self._providers["backend"], 0, 1, 1.0, 0, True)]


@pytest.mark.asyncio
async def test_osworld_run_attributes_agent_to_makima_and_backend_separately() -> None:
    provider = _Provider()
    registry = ToolRegistry(name="osworld-test")
    seen: List[str] = []

    def record_action(value: str) -> Dict[str, Any]:
        seen.append(value)
        return {"success": True}

    registry.register(record_action)
    agent = MakimaOSWorldAgent(
        HermesAgentEngine(router=_Router(provider), enable_implicit_learning=False),
        registry,
    )

    run = await agent.run_task("Click the target", task_id="task-001", observation={"a11y_tree": "button"})

    assert run.agent_name == "Makima"
    assert run.reasoning_backend == "qwen3-alibaba-backend"
    assert run.agent_name != run.reasoning_backend
    assert run.tool_calls_executed == 1
    assert seen == ["clicked"]
    assert OSWORLD_SYSTEM_PROMPT in provider.system_prompts[0]
    assert "internal reasoning backend" in provider.system_prompts[0]


def test_predict_shape_contains_explicit_attribution(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = MakimaOSWorldAgent.__new__(MakimaOSWorldAgent)
    expected = MagicMock(
        agent_name="Makima",
        reasoning_backend="alibaba-model",
        completed=True,
        content="ok",
        tool_calls_executed=2,
        finish_reason="stop",
    )
    monkeypatch.setattr(agent, "run_task", lambda *args, **kwargs: expected)
    # predict uses asyncio.run, so use a real coroutine replacement.
    async def fake_run(*args, **kwargs):
        return expected
    monkeypatch.setattr(agent, "run_task", fake_run)

    result = agent.predict("Do task")
    assert result["agent_name"] == "Makima"
    assert result["reasoning_backend"] == "alibaba-model"


def test_benchmark_router_does_not_mark_unprobed_ollama_available() -> None:
    router = ParetoRouter(strict_local_availability=True)
    router._ollama_probed_models = []
    ollama = next(
        candidate
        for candidate in router.get_ranked_candidates("fast_chat")
        if candidate.name == "ollama"
    )
    assert ollama.is_available is False


def test_osworld_uses_five_alibaba_fallback_models() -> None:
    settings = get_settings(force_reload=True)
    cascade = settings.providers.cascades["osworld"]
    assert len(cascade) >= 8
    assert all(name.startswith("alibaba_") for name in cascade)
    assert all(settings.get_backend(name).api_key_env == "DASHSCOPE_API_KEY" for name in cascade)


def test_official_osworld_runtime_rejects_missing_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSWORLD_ROOT", "C:\\definitely-missing-osworld")
    assert _official_osworld_runtime_available() is False


def test_official_osworld_runtime_is_detected_from_bundled_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OSWORLD_ROOT", raising=False)
    assert _official_osworld_runtime_available() is True
