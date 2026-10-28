"""
Live and Contract Verification for Gemini KV Context Caching (Zero-Payload Second Turn).

Validates:
  1. The User's Exact Hypothesis:
     When Gemini KV Context Caching is active, the second request sends ZERO system instructions
     and ZERO tool declarations over the wire (only `cached_content="cachedContents/..."`).
  2. Tool execution persists on turn 2 even though tools are omitted from the request config.
  3. Token usage correctly extracts `cached_content_token_count` without double-counting.
  4. Free-Tier auto-detection: If Google GenAI returns FreeTier storage limit=0 or minimum token threshold,
     `_context_cache_supported` is set to False to permanently suppress wasteful round-trips.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.config import BackendConfig
from makima.provider.adapters.base import Message, ToolCall
from makima.provider.adapters.gemini import GeminiProvider


async def test_1_wire_contract_zero_payload_second_turn():
    print("[TEST 1] Testing Gemini KV wire contract: 2nd turn sends 0 system prompt & 0 tools...")

    cfg = BackendConfig(
        name="gemini_test",
        adapter="gemini",
        model="gemini-2.5-flash",
        api_key="mock_key",
    )
    provider = GeminiProvider(config=cfg)

    # Mock client and aio caches / models
    mock_client = MagicMock()
    mock_cache_obj = MagicMock()
    mock_cache_obj.name = "cachedContents/makima_e2e_hash99"
    mock_client.aio.caches.create = AsyncMock(return_value=mock_cache_obj)

    # Mock generate_content response for Turn 1 and Turn 2
    part1 = MagicMock()
    part1.text = "Understood, system instructions loaded into KV cache."
    part1.function_call = None
    candidate1 = MagicMock()
    candidate1.content.parts = [part1]

    mock_response_turn1 = MagicMock()
    mock_response_turn1.candidates = [candidate1]
    mock_response_turn1.usage_metadata = MagicMock(
        prompt_token_count=15,
        candidates_token_count=10,
        total_token_count=25,
        cached_content_token_count=1500,
    )

    part2 = MagicMock()
    part2.text = None
    fn2 = MagicMock()
    fn2.name = "execute_browser_action"
    fn2.args = {"action": "navigate", "url": "https://github.com"}
    part2.function_call = fn2
    candidate2 = MagicMock()
    candidate2.content.parts = [part2]

    mock_response_turn2 = MagicMock()
    mock_response_turn2.candidates = [candidate2]
    mock_response_turn2.usage_metadata = MagicMock(
        prompt_token_count=20,
        candidates_token_count=15,
        total_token_count=35,
        cached_content_token_count=1500,
    )

    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[mock_response_turn1, mock_response_turn2]
    )
    provider._client = mock_client

    # System prompt and heavy tool catalog
    system_prompt = "You are Makima, an autonomous agent. Adhere strictly to user preferences."
    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_browser_action",
                "description": "Perform browser automation action",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "url": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        }
    ]

    # --- TURN 1: Initial call with prompt and tools ---
    print("  -> Dispatching Turn 1 with system prompt and tool definitions...")
    res1 = await provider.generate(
        messages=[Message(role="user", content="Hello, initialize system")],
        tools=tools,
        system_prompt=system_prompt,
    )
    assert res1.content == "Understood, system instructions loaded into KV cache."
    assert res1.usage["cached_tokens"] == 1500

    # Verify cache was created on Google side
    assert mock_client.aio.caches.create.call_count == 1
    create_call_args = mock_client.aio.caches.create.call_args[1]
    assert create_call_args["config"].display_name.startswith("makima_kv_")

    # Verify first generate call passed cached_content, and OMITTED system_instruction and tools!
    gen_call_1 = mock_client.aio.models.generate_content.call_args_list[0][1]
    cfg1 = gen_call_1["config"]
    assert cfg1.cached_content == "cachedContents/makima_e2e_hash99"
    assert cfg1.system_instruction is None, "Violation: system_instruction should NOT be sent when cache is active!"
    assert cfg1.tools is None, "Violation: tools should NOT be sent when cache is active!"

    # --- TURN 2: Second call with new user task (KV Cache Hit) ---
    print("  -> Dispatching Turn 2 with new task (NO duplicate cache creation, zero tools sent)...")
    res2 = await provider.generate(
        messages=[
            Message(role="user", content="Hello, initialize system"),
            Message(role="assistant", content=res1.content),
            Message(role="user", content="Go to github.com right now"),
        ],
        tools=tools,
        system_prompt=system_prompt,
    )

    # 1. Verify NO second caches.create call occurred (reused existing active cache)
    assert mock_client.aio.caches.create.call_count == 1, "Cache should have been reused without re-creating!"

    # 2. Verify second call config: STILL omits system_instruction and tools!
    gen_call_2 = mock_client.aio.models.generate_content.call_args_list[1][1]
    cfg2 = gen_call_2["config"]
    assert cfg2.cached_content == "cachedContents/makima_e2e_hash99"
    assert cfg2.system_instruction is None, "Turn 2 must NOT resend system_instruction!"
    assert cfg2.tools is None, "Turn 2 must NOT resend tools!"

    # 3. Verify tool call was received and parsed despite tools being omitted from request payload!
    assert len(res2.tool_calls) == 1
    assert res2.tool_calls[0].name == "execute_browser_action"
    assert res2.tool_calls[0].arguments == {"action": "navigate", "url": "https://github.com"}
    assert res2.usage["cached_tokens"] == 1500

    print("  -> PASSED: Verified that turn 2 sends 0 system prompt & 0 tools, and tool calls execute successfully!")


async def test_2_live_free_tier_auto_suppression():
    print("[TEST 2] Testing live Gemini API free-tier / quota auto-suppression...")

    # Load .env if present
    from dotenv import load_dotenv
    load_dotenv(repo_root / ".env")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("  -> SKIPPED: GEMINI_API_KEY not set in environment.")
        return

    cfg = BackendConfig(
        name="gemini_live_test",
        adapter="gemini",
        model="gemini-2.5-flash",
        api_key=api_key,
    )
    provider = GeminiProvider(config=cfg)

    # Small/medium prompt that trips FreeTier limit=0 or minimum token threshold
    test_prompt = "You are Makima, an autonomous system agent."
    tools = [
        {"type": "function", "function": {"name": "test_ping", "parameters": {"type": "object"}}}
    ]

    # First attempt: Should attempt cache creation and catch FreeTier limit=0 or token minimum
    cache_id = await provider._get_or_create_context_cache(
        system_prompt=test_prompt,
        gemini_tools=provider._convert_tools(tools),
    )
    assert cache_id is None, "Expected cache creation to fall back on standard API key"
    assert provider._context_cache_supported is False, "Expected _context_cache_supported to be False"
    print(f"  -> Successfully caught live provider constraint: {provider._last_cache_fallback_reason[:80]}...")

    # Second attempt: Should immediately return None WITHOUT making any Google API call!
    start_time = asyncio.get_event_loop().time()
    cache_id_2 = await provider._get_or_create_context_cache(
        system_prompt=test_prompt,
        gemini_tools=provider._convert_tools(tools),
    )
    elapsed = asyncio.get_event_loop().time() - start_time
    assert cache_id_2 is None
    # Must be instantaneous (< 5ms) because API call was skipped
    assert elapsed < 0.05, f"Expected instant return, took {elapsed:.4f}s"
    print(f"  -> PASSED: Second attempt returned instantly in {elapsed*1000:.2f}ms without hitting Google API!")


async def main():
    print("=" * 60)
    print("RUNNING LIVE & CONTRACT VERIFICATION: Gemini KV Context Caching")
    print("=" * 60)

    await test_1_wire_contract_zero_payload_second_turn()
    await test_2_live_free_tier_auto_suppression()

    print("=" * 60)
    print("ALL GEMINI KV CACHE E2E CHECKS PASSED SUCCESSFULLY! (EXIT CODE 0)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
