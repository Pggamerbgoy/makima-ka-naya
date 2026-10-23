import asyncio
import os
import sys
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from makima.core.engine import HermesAgentEngine
from makima.provider.adapters.base import ProviderResponse, ToolCall
from makima.provider.router import ParetoRouter
from makima.tools.registry import ToolRegistry


async def main():
    print("Testing Intelligent Parallel Tool Execution in HermesAgentEngine...")

    registry = ToolRegistry(name="test_concurrency")

    execution_timeline = []

    async def safe_fetch_1(query: str) -> str:
        t_start = time.monotonic()
        execution_timeline.append(("fetch_1_start", t_start))
        await asyncio.sleep(0.1)
        t_end = time.monotonic()
        execution_timeline.append(("fetch_1_end", t_end))
        return f"result_1 for {query}"

    async def safe_fetch_2(query: str) -> str:
        t_start = time.monotonic()
        execution_timeline.append(("fetch_2_start", t_start))
        await asyncio.sleep(0.1)
        t_end = time.monotonic()
        execution_timeline.append(("fetch_2_end", t_end))
        return f"result_2 for {query}"

    async def mutating_write(content: str) -> str:
        t_start = time.monotonic()
        execution_timeline.append(("write_start", t_start))
        await asyncio.sleep(0.1)
        t_end = time.monotonic()
        execution_timeline.append(("write_end", t_end))
        return f"wrote: {content}"

    registry.register(safe_fetch_1, name="safe_fetch_1", tags=["search", "web"], parallel_safe=True)
    registry.register(safe_fetch_2, name="safe_fetch_2", tags=["search", "info"], parallel_safe=True)
    registry.register(mutating_write, name="mutating_write", tags=["write", "filesystem"], parallel_safe=False)

    assert registry.is_parallel_safe("safe_fetch_1") is True
    assert registry.is_parallel_safe("safe_fetch_2") is True
    assert registry.is_parallel_safe("mutating_write") is False
    print("  -> Tool registry parallel_safe flags verified.")

    # Mock router that emits 2 parallel-safe calls on turn 1, then a terminating response on turn 2
    class MockRouter(ParetoRouter):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def execute_with_fallback(self, **kwargs) -> ProviderResponse:
            self.calls += 1
            if self.calls == 1:
                return ProviderResponse(
                    content="Let me fetch both in parallel.",
                    model="mock-fast",
                    finish_reason="tool_calls",
                    tool_calls=[
                        ToolCall(id="call_1", name="safe_fetch_1", arguments={"query": "alpha"}),
                        ToolCall(id="call_2", name="safe_fetch_2", arguments={"query": "beta"}),
                    ],
                )
            else:
                # Turn 2: Final response
                messages = kwargs.get("messages", [])
                tool_messages = [m for m in messages if m.role == "tool"]
                assert len(tool_messages) == 2, f"Expected 2 tool outputs, got {len(tool_messages)}"
                assert tool_messages[0].tool_call_id == "call_1"
                assert tool_messages[0].content == "result_1 for alpha"
                assert tool_messages[1].tool_call_id == "call_2"
                assert tool_messages[1].content == "result_2 for beta"
                return ProviderResponse(
                    content="Both fetched successfully.",
                    model="mock-fast",
                    finish_reason="stop",
                    tool_calls=[],
                )

    engine = HermesAgentEngine(router=MockRouter(), max_turns=5)

    t0 = time.monotonic()
    result = await engine.run(prompt="Fetch alpha and beta", tools=registry)
    total_time = time.monotonic() - t0

    print(f"  -> Total execution time: {total_time:.3f}s (sequential would be >= 0.20s)")
    assert result.completed is True
    assert result.tool_calls_executed == 2
    # Since each tool sleeps 0.1s, parallel execution should take ~0.10s-0.15s, NOT >= 0.20s
    assert total_time < 0.18, f"Expected parallel execution < 0.18s, took {total_time:.3f}s"
    print("  -> PASSED: Parallel tool execution verified!")


if __name__ == "__main__":
    asyncio.run(main())
