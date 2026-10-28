"""
Two-Call KV Cache Live Verification Script for Makima v2.

Runs two sequential turns with identical system instructions and tools:
  - Turn 1: Cold start (establishes KV prefix / explicit cache).
  - Turn 2: Hot candidate (verifies cache hit rate and delta cached tokens).

Inspects:
  - result.cached_tokens
  - PromptCacheManager telemetry (/api/status format)
  - Raw provider usage attributes
"""

import asyncio
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from dotenv import load_dotenv
load_dotenv(repo_root / ".env")

from makima.provider.cache import get_cache_manager
from makima.runtime import build_engine, build_registry


async def verify_cache(preferred_backend: str = "gemini"):
    print("=" * 65)
    print(f"RUNNING KV CACHE VERIFICATION ON BACKEND: {preferred_backend}")
    print("=" * 65)

    engine = build_engine()
    registry = build_registry()
    mgr = get_cache_manager()

    # --- Call 1: Cold Cache ---
    print("\n[CALL 1] Cold Start: Generating initial turn...")
    result1 = await engine.run(
        prompt="List 3 main planets in our solar system briefly.",
        tools=registry,
        task="fast_chat",
        preferred_backend=preferred_backend,
    )
    snap1 = mgr.metrics.get_summary()

    print(f"  -> Call 1 Content: {result1.content[:60]}...")
    print(f"  -> Call 1 cached_tokens in result: {result1.cached_tokens}")
    print(f"  -> Call 1 manager total_cached_tokens: {snap1['total_cached_tokens']}")
    print(f"  -> Call 1 cache_hits: {snap1['cache_hits']} / {snap1['total_requests']}")

    # Settle delay
    print("\n[PAUSE] Waiting 1s for provider cache settlement...")
    await asyncio.sleep(1)

    # --- Call 2: Hot Candidate ---
    print("\n[CALL 2] Hot Turn: Same system instructions + tool schemas...")
    result2 = await engine.run(
        prompt="Now name 2 prominent moons of Jupiter briefly.",
        tools=registry,
        task="fast_chat",
        preferred_backend=preferred_backend,
    )
    snap2 = mgr.metrics.get_summary()

    print(f"  -> Call 2 Content: {result2.content[:60]}...")
    print(f"  -> Call 2 cached_tokens in result: {result2.cached_tokens}")
    print(f"  -> Call 2 manager total_cached_tokens: {snap2['total_cached_tokens']}")
    print(f"  -> Call 2 cache_hits: {snap2['cache_hits']} / {snap2['total_requests']}")
    print(f"  -> Call 2 hit_rate: {snap2['cache_hit_rate'] * 100:.1f}%")
    print(f"  -> Call 2 estimated savings: {snap2['estimated_token_savings_pct']:.1f}%")

    delta = snap2["total_cached_tokens"] - snap1["total_cached_tokens"]
    print("-" * 65)
    print(f"DIAGNOSTIC SUMMARY: Delta Cached Tokens = {delta}")
    if delta > 0 or result2.cached_tokens > 0:
        print("  -> RESULT: [PASS] KV Cache IS ACTIVE AND HITTING!")
    else:
        print("  -> RESULT: [NOTICE] Delta is 0. Possible reasons:")
        print("     1. Gemini free-tier key (explicit cache storage limit=0; auto-disabled to save latency).")
        print("     2. Provider uses server-side implicit cache without wire usage reporting (e.g. Ollama).")
        print("     3. System prompt / tool catalog size did not meet provider-specific minimum token floor.")
    print("=" * 65)


if __name__ == "__main__":
    backend = sys.argv[1] if len(sys.argv) > 1 else "gemini"
    asyncio.run(verify_cache(preferred_backend=backend))
