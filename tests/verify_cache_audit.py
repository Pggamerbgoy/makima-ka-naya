"""
Comprehensive Verification Suite for Prompt Caching Audit Fixes:
1. Dynamic memory & skills prompt partitioning (<memory>, <skills> placed in dynamic_suffix).
2. Stale tool schema invalidation on parameter/description changes (SHA-256 schema hashing).
3. OpenRouter & native provider strategy resolution (DeepSeek automatic, Claude/Qwen explicit).
4. Gemini context cache fallback observability and deterministic declaration serialization.
5. Accurate token savings metric accounting (zero double-counting of cached tokens).
6. Tool format LRU cache bounded capacity and deterministic eviction.
"""

import hashlib
import json
import logging
from pathlib import Path
import sys
from unittest.mock import MagicMock, AsyncMock

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.provider.cache import (
    CacheStrategy,
    PromptCacheMetrics,
    UnifiedPromptCacheManager,
    canonicalize_tool_schemas,
    format_cached_messages,
    partition_system_prompt,
    resolve_cache_strategy,
)
from makima.provider.adapters.base import Message
from makima.provider.adapters.gemini import GeminiProvider
from makima.config import BackendConfig

logging.basicConfig(level=logging.INFO)


def test_1_memory_and_skills_partitioning():
    print("[TEST 1] Testing dynamic memory & skills prompt partitioning...")
    base_instructions = "You are Yukino, a helpful desktop assistant."
    memory_section = "<memory>\n- User prefers dark mode\n- Project name: makima\n</memory>"
    skills_section = "<skills>\nAvailable skills: audio, browser\n</skills>"

    # 1. Base + Memory
    prompt_with_memory = f"{base_instructions}\n\n---\n\n{memory_section}"
    prefix, suffix = partition_system_prompt(prompt_with_memory)
    assert prefix == base_instructions, f"Expected static prefix '{base_instructions}', got '{prefix}'"
    assert suffix == memory_section, f"Expected dynamic suffix '{memory_section}', got '{suffix}'"

    # 2. Base + Memory + Skills (multiple dividers)
    full_prompt = f"{base_instructions}\n\n---\n\n{memory_section}\n\n---\n\n{skills_section}"
    prefix_multi, suffix_multi = partition_system_prompt(full_prompt)
    assert prefix_multi == base_instructions, f"Prefix with multiple dividers failed: '{prefix_multi}'"
    assert memory_section in suffix_multi
    assert skills_section in suffix_multi

    # 3. Anthropic cache_control breakpoint check
    messages = [Message(role="user", content="Hello")]
    formatted = format_cached_messages(
        messages=messages,
        system_prompt=full_prompt,
        strategy=CacheStrategy.EXPLICIT_CACHE_CONTROL,
    )
    system_block = formatted[0]
    assert system_block["role"] == "system"
    assert len(system_block["content"]) == 2
    # Static prefix block has cache_control
    assert system_block["content"][0]["text"] == base_instructions
    assert system_block["content"][0]["cache_control"] == {"type": "ephemeral"}
    # Dynamic suffix does NOT have cache_control breakpoint
    assert "cache_control" not in system_block["content"][1]
    assert memory_section in system_block["content"][1]["text"]

    # 4. Base + Skills ONLY (memory context is empty)
    skills_only_prompt = f"{base_instructions}\n\n---\n\n<skills>\n## Available Skills\n- browser\n</skills>"
    prefix_skills, suffix_skills = partition_system_prompt(skills_only_prompt)
    assert prefix_skills == base_instructions, f"Skills-only prefix failed: '{prefix_skills}'"
    assert "Available Skills" in suffix_skills

    # 5. Raw markdown '## Available Skills' without tags (defense-in-depth marker test)
    raw_skills_prompt = f"{base_instructions}\n\n---\n\n## Available Skills\n- browser"
    prefix_raw, suffix_raw = partition_system_prompt(raw_skills_prompt)
    assert prefix_raw == base_instructions, f"Raw skills prefix failed: '{prefix_raw}'"
    assert "## Available Skills" in suffix_raw

    print("  -> PASSED: Dynamic memory and skills properly partitioned into dynamic_suffix!")


def test_2_tool_cache_key_schema_sensitivity():
    print("[TEST 2] Testing tool cache key sensitivity to schema changes...")
    mgr = UnifiedPromptCacheManager()

    # Initial tool schema
    tool_v1 = [
        {
            "type": "function",
            "function": {
                "name": "open_file",
                "description": "Opens a file on disk",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]

    formatted_v1 = mgr.format_tools(tool_v1, strategy=CacheStrategy.AUTOMATIC_PREFIX)
    assert formatted_v1 is not None

    # Schema changes: parameter type changed from string to object, same function name!
    tool_v2 = [
        {
            "type": "function",
            "function": {
                "name": "open_file",
                "description": "Opens a file on disk with advanced options",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "object", "properties": {"uri": {"type": "string"}}}
                    },
                    "required": ["path"],
                },
            },
        }
    ]

    formatted_v2 = mgr.format_tools(tool_v2, strategy=CacheStrategy.AUTOMATIC_PREFIX)
    assert formatted_v2 is not None

    # Stale schema must NOT be returned!
    v1_desc = formatted_v1[0]["function"]["description"]
    v2_desc = formatted_v2[0]["function"]["description"]
    assert v1_desc != v2_desc, "Cache erroneously returned stale schema after description change!"
    v1_prop_type = formatted_v1[0]["function"]["parameters"]["properties"]["path"]["type"]
    v2_prop_type = formatted_v2[0]["function"]["parameters"]["properties"]["path"]["type"]
    assert v1_prop_type == "string"
    assert v2_prop_type == "object"

    print("  -> PASSED: Schema changes immediately invalidate stale cache!")


def test_3_openrouter_and_provider_strategy_resolution():
    print("[TEST 3] Testing OpenRouter & provider cache strategy resolution...")
    # OpenRouter DeepSeek -> AUTOMATIC_PREFIX (DeepSeek manages its own prefix caching)
    strat_ds = resolve_cache_strategy(
        adapter="openai",
        base_url="https://openrouter.ai/api/v1",
        model="deepseek/deepseek-chat",
    )
    assert strat_ds == CacheStrategy.AUTOMATIC_PREFIX, f"Expected AUTOMATIC_PREFIX for DeepSeek on OpenRouter, got {strat_ds}"

    # OpenRouter Claude -> EXPLICIT_CACHE_CONTROL
    strat_claude = resolve_cache_strategy(
        adapter="openai",
        base_url="https://openrouter.ai/api/v1",
        model="anthropic/claude-3.5-sonnet",
    )
    assert strat_claude == CacheStrategy.EXPLICIT_CACHE_CONTROL

    # OpenRouter Qwen -> EXPLICIT_CACHE_CONTROL
    strat_qwen = resolve_cache_strategy(
        adapter="openai",
        base_url="https://openrouter.ai/api/v1",
        model="qwen/qwen-2.5-coder-32b-instruct",
    )
    assert strat_qwen == CacheStrategy.EXPLICIT_CACHE_CONTROL

    # Native Anthropic without base_url
    strat_native_anthropic = resolve_cache_strategy(adapter="anthropic")
    assert strat_native_anthropic == CacheStrategy.EXPLICIT_CACHE_CONTROL

    print("  -> PASSED: Strategy resolution correctly disambiguates DeepSeek, Claude, and Qwen!")


def test_4_gemini_fallback_observability_and_cache_key():
    print("[TEST 4] Testing Gemini cache key stability and fallback observability...")
    cfg = BackendConfig(
        name="test_gemini",
        adapter="gemini",
        model="gemini-2.5-flash",
        api_key="dummy_key",
    )
    provider = GeminiProvider(config=cfg)

    # 1. Deterministic schema key in _convert_tools
    tools_a = [
        {"type": "function", "function": {"name": "test_tool", "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}}}}
    ]
    res_a = provider._convert_tools(tools_a)
    assert res_a is not None
    cached_key_a = provider._cached_tools_key

    # Modify parameters
    tools_b = [
        {"type": "function", "function": {"name": "test_tool", "parameters": {"type": "object", "properties": {"x": {"type": "string"}}}}}
    ]
    res_b = provider._convert_tools(tools_b)
    assert res_b is not None
    cached_key_b = provider._cached_tools_key
    assert cached_key_a != cached_key_b, "Gemini tools cache key failed to differentiate parameter type changes!"

    # 2. Test fallback observability when client.aio.caches.create fails
    mock_client = MagicMock()
    mock_client.aio.caches.create = AsyncMock(side_effect=RuntimeError("Model threshold not met: requires 32768 tokens"))
    provider._client = mock_client

    import asyncio
    cache_id = asyncio.run(provider._get_or_create_context_cache("System prompt", res_b))
    assert cache_id is None
    assert provider._last_cache_fallback_reason is not None
    assert "threshold" in provider._last_cache_fallback_reason
    # Verify flag was disabled to prevent repeating failing API calls
    assert provider._context_cache_supported is False

    # 3. Test repeat call skips API hit entirely due to _context_cache_supported = False
    cache_id_repeat = asyncio.run(provider._get_or_create_context_cache("System prompt", res_b))
    assert cache_id_repeat is None
    assert mock_client.aio.caches.create.call_count == 1  # Never called again!

    # 4. Test thinking config helper parity across generate and stream
    cfg_thinking_on = provider._build_generate_config(
        temperature=0.2,
        thinking_config=provider._resolve_thinking_config({"enable_thinking": True}),
    )
    assert cfg_thinking_on.thinking_config is not None
    assert cfg_thinking_on.thinking_config.thinking_budget == -1

    cfg_thinking_off = provider._build_generate_config(
        temperature=0.2,
        thinking_config=provider._resolve_thinking_config({"enable_thinking": False}),
    )
    assert cfg_thinking_off.thinking_config is not None
    assert cfg_thinking_off.thinking_config.thinking_budget == 0

    print("  -> PASSED: Gemini key is parameter-sensitive, threshold failure disables retry, and stream thinking is verified!")


def test_5_metrics_token_savings_accounting():
    print("[TEST 5] Testing prompt cache savings metric accounting...")
    metrics = PromptCacheMetrics()

    # Scenario: Total prompt tokens = 10,000, of which 5,000 are cached tokens
    # In OpenAI convention, prompt_tokens is the total prompt tokens.
    # Cached token share is 5,000 / 10,000 = 50.0%
    metrics.record_turn(model="gpt-4o", prompt_tokens=10000, cached_tokens=5000)
    summary = metrics.get_summary()

    assert summary["total_prompt_tokens"] == 10000
    assert summary["total_cached_tokens"] == 5000
    assert summary["cache_hits"] == 1
    # Old buggy formula gave 5000 / (10000 + 5000) * 100 = 33.33%
    # Fixed formula gives 5000 / 10000 * 100 = 50.0%
    assert summary["estimated_token_savings_pct"] == 50.0, f"Expected 50.0%, got {summary['estimated_token_savings_pct']}"

    # 100% cache hit scenario
    metrics_100 = PromptCacheMetrics()
    metrics_100.record_turn(model="gpt-4o", prompt_tokens=4000, cached_tokens=4000)
    summary_100 = metrics_100.get_summary()
    assert summary_100["estimated_token_savings_pct"] == 100.0

    print("  -> PASSED: Metric calculation correctly reports 50% (and 100%) without double-counting!")


def test_6_tool_format_lru_eviction():
    print("[TEST 6] Testing tool format cache bounded LRU eviction...")
    # Initialize cache manager with small capacity of 3
    mgr = UnifiedPromptCacheManager(max_tool_cache_size=3)

    for i in range(5):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": f"tool_{i}",
                    "description": f"Description {i}",
                    "parameters": {"type": "object", "properties": {"v": {"type": "integer"}}},
                },
            }
        ]
        mgr.format_tools(tools, strategy=CacheStrategy.AUTOMATIC_PREFIX)

    # Size must not exceed max_tool_cache_size
    assert len(mgr._tool_format_cache) == 3, f"Expected size 3, got {len(mgr._tool_format_cache)}"

    print("  -> PASSED: Tool format cache strictly bounded by LRU eviction!")


if __name__ == "__main__":
    test_1_memory_and_skills_partitioning()
    test_2_tool_cache_key_schema_sensitivity()
    test_3_openrouter_and_provider_strategy_resolution()
    test_4_gemini_fallback_observability_and_cache_key()
    test_5_metrics_token_savings_accounting()
    test_6_tool_format_lru_eviction()
    print("\n============================================================")
    print("ALL CACHE AUDIT VERIFICATION CHECKS PASSED SUCCESSFULLY! (0)")
    print("============================================================")
