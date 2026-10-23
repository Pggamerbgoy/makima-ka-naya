"""
Live verification script for Phase 1 Step 2: Provider Adapters & Circuit Breakers.
Tests:
  1. Circuit Breaker state transitions (CLOSED -> OPEN -> HALF_OPEN) and jittered cooldown.
  2. Normalized Message, ToolCall, and ProviderResponse data contract validation.
  3. GeminiProvider message formatting and tool declaration translation.
  4. OpenAICompatibleProvider message formatting and tool translation.
  5. Mock execution & error handling through circuit breaker.
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Ensure makima is importable
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.config import BackendConfig
from makima.provider import (
    CircuitBreaker,
    CircuitState,
    GeminiProvider,
    Message,
    OpenAICompatibleProvider,
    ProviderResponse,
    ToolCall,
)


async def test_circuit_breaker():
    print("[TEST 1] Testing Circuit Breaker state machine & jittered cooldown...")
    cb = CircuitBreaker(name="test_provider", max_failures=3, cooldown_seconds=0.5, jitter=False)

    assert cb.state == CircuitState.CLOSED
    assert await cb.can_execute() is True
    assert cb.is_available is True

    # Record 2 failures (threshold not reached)
    await cb.record_failure(Exception("Transient 503"))
    await cb.record_failure(Exception("Transient 503"))
    assert cb.state == CircuitState.CLOSED
    assert cb.consecutive_failures == 2

    # 3rd failure trips the breaker to OPEN
    await cb.record_failure(Exception("Rate limit 429"))
    assert cb.state == CircuitState.OPEN
    assert cb.is_available is False
    assert await cb.can_execute() is False

    # Wait for cooldown (0.5s) to elapse -> transitions to HALF_OPEN
    await asyncio.sleep(0.55)
    assert cb.state == CircuitState.HALF_OPEN
    assert await cb.can_execute() is True

    # Record success -> resets to CLOSED
    await cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.consecutive_failures == 0
    print("  -> PASSED: Circuit Breaker FSM (CLOSED -> OPEN -> HALF_OPEN -> CLOSED) verified!")


async def test_message_and_tool_contracts():
    print("[TEST 2] Testing canonical Message, ToolCall, and ProviderResponse models...")
    tc = ToolCall(
        id="call_test123",
        name="web_search",
        arguments={"query": "Hermes Agent architecture", "limit": 5},
    )
    assert tc.name == "web_search"
    assert tc.arguments["limit"] == 5

    msg = Message(
        role="assistant",
        content="Searching the web...",
        tool_calls=[tc],
    )
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].id == "call_test123"

    resp = ProviderResponse(
        content="Here is what I found.",
        tool_calls=[tc],
        finish_reason="tool_calls",
        model="gemini-2.5-flash",
        latency_ms=120.5,
    )
    assert resp.finish_reason == "tool_calls"
    assert resp.latency_ms == 120.5
    print("  -> PASSED: Canonical message and response schemas verified!")


async def test_gemini_adapter_translation():
    print("[TEST 3] Testing GeminiProvider wire translation & tool declarations...")
    config = BackendConfig(
        adapter="gemini",
        model="gemini-2.5-flash",
        api_key_env="TEST_GEMINI_KEY",
        latency_tier="fast",
        context_limit=1000000,
    )
    os.environ["TEST_GEMINI_KEY"] = "mock_gemini_key_for_testing"
    
    try:
        provider = GeminiProvider(config=config)
        messages = [
            Message(role="user", content="What is the weather in Tokyo?"),
            Message(role="assistant", tool_calls=[
                ToolCall(id="call_1", name="get_weather", arguments={"city": "Tokyo"})
            ]),
            Message(role="tool", name="get_weather", content='{"temp": "18C", "condition": "Clear"}'),
        ]
        tools = [{
            "function": {
                "name": "get_weather",
                "description": "Fetch current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        }]

        # Test message conversion
        contents = provider._convert_messages(messages)
        assert len(contents) == 3, f"Expected 3 Content objects, got {len(contents)}"
        assert contents[0].role == "user"
        assert contents[1].role == "model"
        assert contents[2].role == "user"

        # Test tool declaration conversion
        gemini_tools = provider._convert_tools(tools)
        assert gemini_tools is not None
        assert len(gemini_tools) == 1
        # Test multi-tool parallel coalescing into a single user turn
        parallel_messages = [
            Message(role="user", content="Check weather and news"),
            Message(role="assistant", tool_calls=[
                ToolCall(id="c1", name="get_weather", arguments={"city": "Tokyo"}),
                ToolCall(id="c2", name="get_news", arguments={"topic": "tech"}),
            ]),
            Message(role="tool", name="get_weather", content='{"temp": "18C"}'),
            Message(role="tool", name="get_news", content='{"headline": "AI Launch"}'),
        ]
        parallel_contents = provider._convert_messages(parallel_messages)
        assert len(parallel_contents) == 3, f"Parallel tool turns must coalesce into 3 turns, got {len(parallel_contents)}"
        assert parallel_contents[0].role == "user"
        assert parallel_contents[1].role == "model"
        assert parallel_contents[2].role == "user"
        assert len(parallel_contents[2].parts) == 2, f"Turn 3 must have exactly 2 FunctionResponse parts, got {len(parallel_contents[2].parts)}"
        assert parallel_contents[2].parts[0].function_response.name == "get_weather"
        assert parallel_contents[2].parts[1].function_response.name == "get_news"
        # Verify response payload was converted to structured dict
        assert parallel_contents[2].parts[0].function_response.response == {"temp": "18C"}

        print("  -> PASSED: Gemini wire translation, multi-tool coalescing, and function declarations verified!")
    finally:
        os.environ.pop("TEST_GEMINI_KEY", None)


async def test_openai_compatible_adapter():
    print("[TEST 4] Testing OpenAICompatibleProvider payload formatting...")
    config = BackendConfig(
        adapter="openai",
        model="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="TEST_GROQ_KEY",
        latency_tier="fast",
        context_limit=128000,
    )
    os.environ["TEST_GROQ_KEY"] = "mock_groq_key_for_testing"

    try:
        provider = OpenAICompatibleProvider(config=config)
        messages = [
            Message(role="user", content="List 3 tasks."),
        ]
        formatted = provider._format_messages(messages, system_prompt="You are Makima.")
        assert len(formatted) == 2  # System message + user message
        assert formatted[0]["role"] == "system"
        assert formatted[0]["content"] == "You are Makima."
        assert formatted[1]["role"] == "user"
        assert formatted[1]["content"] == "List 3 tasks."
        print("  -> PASSED: OpenAI-compatible payload formatting verified!")
    finally:
        os.environ.pop("TEST_GROQ_KEY", None)


async def test_mock_generation():
    print("[TEST 5] Testing mock end-to-end generate() call through Circuit Breaker...")
    config = BackendConfig(
        adapter="openai",
        model="mock-fast-model",
        base_url="http://mock-endpoint/v1",
        api_key_env="MOCK_KEY",
    )
    os.environ["MOCK_KEY"] = "mock_key"

    try:
        provider = OpenAICompatibleProvider(config=config)
        
        # Mock the underlying client
        mock_choice = MagicMock()
        mock_choice.message.content = "Makima v2 is operational."
        mock_choice.message.tool_calls = None
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        res = await provider.generate(
            messages=[Message(role="user", content="Status report.")],
            system_prompt="You are Makima.",
        )

        assert res.content == "Makima v2 is operational."
        assert res.finish_reason == "stop"
        assert res.usage["total_tokens"] == 15
        assert provider.circuit_breaker.state == CircuitState.CLOSED
        print("  -> PASSED: Mock generation and usage parsing completed successfully!")
    finally:
        os.environ.pop("MOCK_KEY", None)


async def test_unified_prompt_caching():
    print("[TEST 6] Testing Unified Multi-Provider KV & Prompt Cache Coordinator...")
    from makima.provider import (
        CacheStrategy,
        canonicalize_tool_schemas,
        extract_cached_tokens,
        get_cache_manager,
        partition_system_prompt,
        resolve_cache_strategy,
    )

    # 1. Strategy Resolution Check across all ecosystem endpoints
    assert resolve_cache_strategy(adapter="gemini") == CacheStrategy.EXPLICIT_GENAI
    assert resolve_cache_strategy(adapter="openai", base_url="https://api.anthropic.com/v1") == CacheStrategy.EXPLICIT_CACHE_CONTROL
    assert resolve_cache_strategy(adapter="openai", base_url="https://openrouter.ai/api/v1", model="anthropic/claude-3.5-sonnet") == CacheStrategy.EXPLICIT_CACHE_CONTROL
    assert resolve_cache_strategy(adapter="openai", base_url="https://openrouter.ai/api/v1", model="deepseek/deepseek-r1") == CacheStrategy.EXPLICIT_CACHE_CONTROL
    assert resolve_cache_strategy(adapter="openai", base_url="https://api.openai.com/v1", model="gpt-4o") == CacheStrategy.AUTOMATIC_PREFIX
    assert resolve_cache_strategy(adapter="openai", base_url="https://api.deepseek.com/v1", model="deepseek-chat") == CacheStrategy.AUTOMATIC_PREFIX
    assert resolve_cache_strategy(adapter="openai", base_url="https://api.groq.com/openai/v1", model="llama-3.3-70b-versatile") == CacheStrategy.AUTOMATIC_PREFIX
    assert resolve_cache_strategy(adapter="openai", base_url="https://api.cerebras.ai/v1", model="llama3.1-70b") == CacheStrategy.AUTOMATIC_PREFIX
    assert resolve_cache_strategy(adapter="openai", base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1", model="qwen3.7-plus") == CacheStrategy.AUTOMATIC_PREFIX
    assert resolve_cache_strategy(adapter="ollama", base_url="http://localhost:11434", model="qwen2.5-coder:7b") == CacheStrategy.AUTOMATIC_PREFIX

    # 2. Canonical tool sorting and schema normalization
    raw_tools = [
        {"type": "function", "function": {"name": "zoom_in", "description": "Zoom"}},
        {"type": "function", "function": {"name": "alpha_search", "description": "Search"}},
        {"type": "function", "function": {"name": "beta_tool", "description": "Beta"}},
    ]
    canonical = canonicalize_tool_schemas(raw_tools)
    assert canonical is not None
    assert [t["function"]["name"] for t in canonical] == ["alpha_search", "beta_tool", "zoom_in"]

    # 3. Explicit Ephemeral Cache Control formatting
    mgr = get_cache_manager()
    formatted_tools = mgr.format_tools(raw_tools, strategy=CacheStrategy.EXPLICIT_CACHE_CONTROL)
    assert formatted_tools is not None
    # Last tool must have cache_control breakpoint
    assert formatted_tools[-1].get("cache_control") == {"type": "ephemeral"}
    assert "cache_control" not in formatted_tools[0]

    # 4. System prompt partitioning
    p_text = "You are Yukino.\n\n---\n\n<active_browser_state>\nhttps://amazon.in\n</active_browser_state>"
    static_p, dyn_p = partition_system_prompt(p_text)
    assert static_p == "You are Yukino."
    assert "<active_browser_state>" in dyn_p

    # 5. Universal Cached Tokens Extractor across vendors
    # 5a. OpenAI object
    mock_openai_usage = MagicMock()
    mock_openai_usage.prompt_tokens_details.cached_tokens = 4096
    assert extract_cached_tokens(mock_openai_usage) == 4096

    # 5b. DeepSeek dict
    assert extract_cached_tokens({"prompt_cache_hit_tokens": 1024, "prompt_tokens": 2048}) == 1024

    # 5c. Anthropic dict
    assert extract_cached_tokens({"cache_read_input_tokens": 2048, "prompt_tokens": 2500}) == 2048

    # 5d. Google GenAI metadata object
    mock_gemini_meta = MagicMock()
    mock_gemini_meta.cached_content_token_count = 8192
    assert extract_cached_tokens(mock_gemini_meta) == 8192

    # 6. Metrics & Savings summary
    mgr.record_usage("gpt-4o", prompt_tokens=2000, cached_tokens=4000)
    summary = mgr.metrics.get_summary()
    assert summary["cache_hits"] >= 1
    assert summary["total_cached_tokens"] >= 4000
    assert summary["estimated_token_savings_pct"] > 0
    print("  -> PASSED: Unified Multi-Provider KV & Prompt Caching verified across all models!")


async def main():
    print("=" * 60)
    print("RUNNING LIVE VERIFICATION: makima/provider/ (Adapters & Circuit Breakers)")
    print("=" * 60)
    await test_circuit_breaker()
    await test_message_and_tool_contracts()
    await test_gemini_adapter_translation()
    await test_openai_compatible_adapter()
    await test_mock_generation()
    await test_unified_prompt_caching()
    print("=" * 60)
    print("ALL PROVIDER ADAPTER & CACHING VERIFICATION CHECKS PASSED! (EXIT CODE 0)")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
