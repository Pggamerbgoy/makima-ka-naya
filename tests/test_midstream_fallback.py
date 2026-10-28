"""
Unit tests for Feature 1: Multi-Provider Mid-Stream Fallback & Dynamic Routing.
Verifies seamless mid-stream failover across providers when connection drops or rate limits occur.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional
import pytest

from makima.config import BackendConfig
from makima.provider.adapters.base import (
    BaseProvider,
    Message,
    ProviderResponse,
    StreamChunk,
)
from makima.provider.circuit_breaker import CircuitBreaker
from makima.provider.router import ParetoRouter, ProviderMetrics


class MockStreamProvider(BaseProvider):
    """
    Controllable mock provider for streaming & fallback testing.
    """

    def __init__(
        self,
        name: str,
        chunks: List[str],
        fail_midstream: bool = False,
        fail_prestream: bool = False,
    ):
        cfg = BackendConfig(adapter="openai", model=name, latency_tier="fast")
        cb = CircuitBreaker(name=name, max_failures=5, cooldown_seconds=60)
        super().__init__(config=cfg, circuit_breaker=cb)
        self.name = name
        self._chunks = chunks
        self.fail_midstream = fail_midstream
        self.fail_prestream = fail_prestream
        self.received_messages: List[List[Message]] = []

    @property
    def is_available(self) -> bool:
        return True

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> ProviderResponse:
        self.received_messages.append(list(messages))
        if self.fail_prestream:
            raise RuntimeError(f"{self.name} generate failed")
        return ProviderResponse(
            content="".join(self._chunks),
            finish_reason="stop",
            model=self.name,
        )

    async def stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        self.received_messages.append(list(messages))

        if self.fail_prestream:
            raise RuntimeError(f"{self.name} failed before yielding any chunks")

        for idx, text in enumerate(self._chunks):
            yield StreamChunk(delta=text, finish_reason=None if idx < len(self._chunks) - 1 else "stop")

        if self.fail_midstream:
            raise RuntimeError("Mid-stream connection drop")


class MockNonStreamProvider(BaseProvider):
    """Mock provider where stream raises NotImplementedError (generate only)."""

    def __init__(self, name: str, content: str):
        cfg = BackendConfig(adapter="openai", model=name, latency_tier="fast")
        cb = CircuitBreaker(name=name, max_failures=5, cooldown_seconds=60)
        super().__init__(config=cfg, circuit_breaker=cb)
        self.name = name
        self.content = content
        self.received_messages: List[List[Message]] = []

    @property
    def is_available(self) -> bool:
        return True

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> ProviderResponse:
        self.received_messages.append(list(messages))
        return ProviderResponse(
            content=self.content,
            finish_reason="stop",
            model=self.name,
        )

    async def stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError("Streaming not supported on this provider")
        if False:
            yield StreamChunk()


def _setup_router_with_mock_cascade(
    providers: Dict[str, BaseProvider],
    cascade_names: List[str],
    task_name: str = "test_stream",
) -> ParetoRouter:
    """Helper to configure a ParetoRouter with explicit mock providers."""
    router = ParetoRouter()
    router._initialized = True
    router._providers = dict(providers)
    router._metrics = {name: ProviderMetrics(default_latency_ms=100.0) for name in providers}
    router.settings.providers.cascades[task_name] = cascade_names
    return router


@pytest.mark.asyncio
async def test_midstream_fallback_success():
    """
    Core test:
    - Provider A yields 3 chunks ("Hello world, ", "today we will ", "explore ") and then raises RuntimeError.
    - Provider B succeeds with ("the universe in detail.").
    - All chunks are emitted to on_chunk in order.
    - Result contains the complete merged text without re-raising.
    """
    provider_a = MockStreamProvider(
        name="provider_a",
        chunks=["Hello world, ", "today we will ", "explore "],
        fail_midstream=True,
    )
    provider_b = MockStreamProvider(
        name="provider_b",
        chunks=["the universe in detail."],
        fail_midstream=False,
    )

    router = _setup_router_with_mock_cascade(
        providers={"provider_a": provider_a, "provider_b": provider_b},
        cascade_names=["provider_a", "provider_b"],
    )

    emitted_chunks: List[str] = []

    def on_chunk(delta: str) -> None:
        emitted_chunks.append(delta)

    user_msg = Message(role="user", content="Tell me about astronomy.")
    resp = await router.execute_with_fallback(
        task="test_stream",
        messages=[user_msg],
        on_chunk=on_chunk,
    )

    # 1. Assert all chunks were emitted to on_chunk in exact sequence
    assert emitted_chunks == [
        "Hello world, ",
        "today we will ",
        "explore ",
        "the universe in detail.",
    ]

    # 2. Assert final result contains complete merged text
    expected_full_text = "Hello world, today we will explore the universe in detail."
    assert resp.content == expected_full_text
    assert resp.finish_reason == "stop"
    assert resp.model == "provider_b"

    # 3. Assert metrics recorded correctly
    assert router._metrics["provider_a"].failed_requests == 1
    assert router._metrics["provider_b"].successful_requests == 1

    # 4. Assert Provider B received continuation prompt with assistant prefix and directive
    assert len(provider_b.received_messages) == 1
    b_msgs = provider_b.received_messages[0]
    assert len(b_msgs) == 3
    assert b_msgs[0] == user_msg
    assert b_msgs[1].role == "assistant"
    assert b_msgs[1].content == "Hello world, today we will explore "
    assert b_msgs[2].role == "user"
    assert "[SYSTEM DIRECTIVE: The previous model stream disconnected mid-sentence." in b_msgs[2].content
    assert "Do NOT repeat or restart: 'Hello world, today we will explore ']" in b_msgs[2].content


@pytest.mark.asyncio
async def test_midstream_fallback_with_async_chunk_handler():
    """Verifies that asynchronous on_chunk callbacks are properly awaited during fallback."""
    provider_a = MockStreamProvider(
        name="provider_a",
        chunks=["Hello world, ", "today we will ", "explore "],
        fail_midstream=True,
    )
    provider_b = MockStreamProvider(
        name="provider_b",
        chunks=["the universe in detail."],
        fail_midstream=False,
    )

    router = _setup_router_with_mock_cascade(
        providers={"provider_a": provider_a, "provider_b": provider_b},
        cascade_names=["provider_a", "provider_b"],
    )

    emitted_chunks: List[str] = []

    async def async_on_chunk(delta: str) -> None:
        await asyncio.sleep(0.001)
        emitted_chunks.append(delta)

    resp = await router.execute_with_fallback(
        task="test_stream",
        messages=[Message(role="user", content="Query")],
        on_chunk=async_on_chunk,
    )

    assert emitted_chunks == [
        "Hello world, ",
        "today we will ",
        "explore ",
        "the universe in detail.",
    ]
    assert resp.content == "Hello world, today we will explore the universe in detail."


@pytest.mark.asyncio
async def test_midstream_fallback_to_non_streaming_provider():
    """Verifies fallback when Provider B does not support stream (falls back to generate)."""
    provider_a = MockStreamProvider(
        name="provider_a",
        chunks=["Hello world, ", "today we will ", "explore "],
        fail_midstream=True,
    )
    provider_b = MockNonStreamProvider(
        name="provider_b",
        content="the universe in detail.",
    )

    router = _setup_router_with_mock_cascade(
        providers={"provider_a": provider_a, "provider_b": provider_b},
        cascade_names=["provider_a", "provider_b"],
    )

    emitted_chunks: List[str] = []

    def on_chunk(delta: str) -> None:
        emitted_chunks.append(delta)

    resp = await router.execute_with_fallback(
        task="test_stream",
        messages=[Message(role="user", content="Query")],
        on_chunk=on_chunk,
    )

    assert emitted_chunks == [
        "Hello world, ",
        "today we will ",
        "explore ",
        "the universe in detail.",
    ]
    assert resp.content == "Hello world, today we will explore the universe in detail."


@pytest.mark.asyncio
async def test_midstream_fallback_multiple_failures_exhaustion():
    """Verifies that if both providers fail midstream, RuntimeError is raised."""
    provider_a = MockStreamProvider(
        name="provider_a",
        chunks=["Part 1, "],
        fail_midstream=True,
    )
    provider_b = MockStreamProvider(
        name="provider_b",
        chunks=["Part 2, "],
        fail_midstream=True,
    )

    router = _setup_router_with_mock_cascade(
        providers={"provider_a": provider_a, "provider_b": provider_b},
        cascade_names=["provider_a", "provider_b"],
    )

    emitted_chunks: List[str] = []

    with pytest.raises(RuntimeError, match="All providers exhausted"):
        await router.execute_with_fallback(
            task="test_stream",
            messages=[Message(role="user", content="Query")],
            on_chunk=lambda d: emitted_chunks.append(d),
        )

    # Both parts were emitted before total failure
    assert emitted_chunks == ["Part 1, ", "Part 2, "]


@pytest.mark.asyncio
async def test_prestream_failure_does_not_use_midstream_directive():
    """Verifies that failure before any chunk emits does not trigger midstream continuation."""
    provider_a = MockStreamProvider(
        name="provider_a",
        chunks=["Chunk A"],
        fail_prestream=True,
    )
    provider_b = MockStreamProvider(
        name="provider_b",
        chunks=["Complete clean response."],
        fail_midstream=False,
    )

    router = _setup_router_with_mock_cascade(
        providers={"provider_a": provider_a, "provider_b": provider_b},
        cascade_names=["provider_a", "provider_b"],
    )

    emitted_chunks: List[str] = []
    user_msg = Message(role="user", content="Fresh query")

    resp = await router.execute_with_fallback(
        task="test_stream",
        messages=[user_msg],
        on_chunk=lambda d: emitted_chunks.append(d),
    )

    assert emitted_chunks == ["Complete clean response."]
    assert resp.content == "Complete clean response."
    # Provider B should only have received original user_msg without continuation directive
    assert len(provider_b.received_messages[0]) == 1
    assert provider_b.received_messages[0][0] == user_msg
