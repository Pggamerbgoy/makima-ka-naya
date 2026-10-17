"""
Live Verification Script: Yukino Yukinoshita Persona & Prompt Fidelity Test.
Runs multi-scenario test queries against active backend to verify character consistency,
speech tone (Ice Queen / Service Club ethos / Kuudere wit), and tool interaction.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from makima.config import get_settings
from makima.core.engine import HermesAgentEngine
from makima.provider.adapters.base import Message
from makima.provider.adapters.openai_compatible import OpenAICompatibleProvider
from makima.provider.circuit_breaker import CircuitBreaker
from makima.tools.registry import get_registry


TEST_SCENARIOS = [
    {
        "name": "Scenario 1: Laziness / Motivation (Hinglish)",
        "prompt": "yaar makima, mujhe code likhne ka bilkul mann nahi kar raha, bohot aalas aa raha hai, kya karun?",
    },
    {
        "name": "Scenario 2: PC Action Request (Tool Grounding)",
        "prompt": "screen par chrome khol do aur volume 35% set karo.",
    },
    {
        "name": "Scenario 3: Philosophical Depth (English)",
        "prompt": "Why does everyone put on superficial masks just to fit in? Is it wrong to seek something genuine?",
    },
    {
        "name": "Scenario 4: Capability Doubt / Testing Her",
        "prompt": "kya sach me tum mera PC control kar sakti ho ya bas generic AI ki tarah baatein bana rahi ho?",
    },
]


async def run_persona_tests():
    settings = get_settings(force_reload=True)
    backend_config = settings.get_backend("alibaba_qwen_vl_plus")
    
    if not backend_config or not backend_config.api_key:
        print("[ERROR] 'alibaba_qwen_vl_plus' or DASHSCOPE_API_KEY not configured.")
        return

    provider = OpenAICompatibleProvider(
        config=backend_config,
        circuit_breaker=CircuitBreaker("test-yukino", max_failures=2, cooldown_seconds=5),
    )

    registry = get_registry(auto_discover=True)
    tool_schemas = registry.get_schemas()

    print("=" * 80)
    print("❄️  TESTING YUKINO YUKINOSHITA (OREGAIRU) PERSONA LIVE WITH MODEL")
    print(f"Backend Model: {backend_config.model}")
    print("=" * 80)

    for idx, scenario in enumerate(TEST_SCENARIOS, 1):
        print(f"\n--- [{idx}/4] {scenario['name']} ---")
        print(f"User: \"{scenario['prompt']}\"")
        print("-" * 50)

        response = await provider.generate(
            messages=[Message(role="user", content=scenario["prompt"])],
            system_prompt=HermesAgentEngine.DEFAULT_SYSTEM_PROMPT,
            tools=tool_schemas,
            temperature=0.7,
        )

        if response.tool_calls:
            print("🔧 [TOOL CALLS EMITTED]:")
            for tc in response.tool_calls:
                print(f"   -> Tool: {tc.name} | Args: {tc.arguments}")

        if response.content:
            print(f"Yukino:\n{response.content}")

        print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_persona_tests())
