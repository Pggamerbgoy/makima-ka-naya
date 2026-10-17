"""
Live verification script for Phase 1 Step 3: Dynamic Zero-Cost ParetoRouter (makima/provider/router.py).
Tests:
  1. Live/mock Ollama detection and model discovery.
  2. Candidate ranking order along Pareto frontier for 'fast_chat', 'code', and 'offline'.
  3. EWMA latency updates on successful responses (math & runtime integration).
  4. Automatic fallback along task cascade when a primary provider encounters a failure or tripped circuit breaker.
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.WARNING,
    format="[%(levelname)s] %(message)s",
    stream=sys.stdout,
)

# Ensure makima is importable
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.config import get_settings
from makima.provider import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    Message,
    ParetoCandidate,
    ParetoRouter,
    ProviderMetrics,
    ProviderResponse,
)


# ==============================================================================
# TEST 1: Live & Mock Ollama Detection and Model Discovery
# ==============================================================================
async def test_ollama_discovery():
    print("[TEST 1] Testing Ollama Detection and Model Discovery...")

    # 1.1 Live Probe (probe localhost:11434 if daemon is active)
    router = ParetoRouter()
    live_models = await router.probe_ollama()
    print(f"  -> Live Ollama probe result: {live_models} (Daemon reachable: {len(live_models) > 0})")
    assert isinstance(live_models, list)
    assert router.ollama_probed_models == live_models

    # 1.2 Mocked Probe (Success with multiple models)
    mock_payload = {
        "models": [
            {"name": "qwen2.5-coder:7b"},
            {"name": "llama3.2:3b"},
            {"name": "deepseek-r1:8b"},
        ]
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        discovered = await router.probe_ollama()
        assert discovered == ["qwen2.5-coder:7b", "llama3.2:3b", "deepseek-r1:8b"]
        assert router.ollama_probed_models == ["qwen2.5-coder:7b", "llama3.2:3b", "deepseek-r1:8b"]
        print("  -> PASSED: Mocked model discovery parsed 3 active local models!")

    # 1.3 Mocked Probe (Daemon offline / Connection Refused)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection refused to localhost:11434")
        discovered_offline = await router.probe_ollama()
        assert discovered_offline == []
        assert router.ollama_probed_models == []
        print("  -> PASSED: Offline daemon handled gracefully with empty model list!")


# ==============================================================================
# TEST 2: Candidate Ranking Order along Pareto Frontier
# ==============================================================================
async def test_candidate_ranking_pareto_frontier():
    print("[TEST 2] Testing candidate ranking along Pareto frontier for 'fast_chat', 'code', and 'offline'...")

    # Set mock credentials for cloud providers
    env_backup = {
        k: os.environ.get(k)
        for k in ["GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"]
    }
    os.environ["GROQ_API_KEY"] = "mock_groq_key"
    os.environ["GEMINI_API_KEY"] = "mock_gemini_key"
    os.environ["OPENROUTER_API_KEY"] = "mock_openrouter_key"

    try:
        router = ParetoRouter()

        # 2.1 fast_chat cascade verification
        # Expected cascade: ["gemini", "groq", "openrouter_free", "ollama"]
        fast_candidates = router.get_ranked_candidates("fast_chat")
        fast_names = [c.name for c in fast_candidates]
        assert fast_names == ["gemini", "groq", "openrouter_free", "ollama"], (
            f"Unexpected fast_chat ranking: {fast_names}"
        )
        selected_fast = router.select_provider("fast_chat")
        assert selected_fast.name == "gemini-2.5-flash"  # Gemini's model
        print(f"  -> PASSED: fast_chat ranking verified: {fast_names} -> Selected: {selected_fast.name}")

        # 2.2 code cascade verification
        # Expected cascade: ["ollama", "groq", "openrouter_free", "gemini"]
        code_candidates = router.get_ranked_candidates("code")
        code_names = [c.name for c in code_candidates]
        assert code_names == ["ollama", "groq", "openrouter_free", "gemini"], (
            f"Unexpected code ranking: {code_names}"
        )
        selected_code = router.select_provider("code")
        assert selected_code.name == "qwen2.5-coder:7b"  # Ollama's model
        print(f"  -> PASSED: code ranking verified: {code_names} -> Selected: {selected_code.name}")

        # 2.3 offline cascade verification
        # Expected cascade: ["ollama"]
        offline_candidates = router.get_ranked_candidates("offline")
        offline_names = [c.name for c in offline_candidates]
        assert offline_names == ["ollama"], f"Unexpected offline ranking: {offline_names}"
        selected_offline = router.select_provider("offline")
        assert selected_offline.name == "qwen2.5-coder:7b"
        print(f"  -> PASSED: offline ranking verified: {offline_names} -> Selected: {selected_offline.name}")

        # 2.4 Local-only / Zero Cloud Keys Mode verification
        # When cloud API keys are stripped, Ollama MUST automatically emerge as rank #1
        os.environ.pop("GROQ_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("OPENROUTER_API_KEY", None)

        local_only_router = ParetoRouter()
        local_fast_candidates = local_only_router.get_ranked_candidates("fast_chat")
        assert local_fast_candidates[0].name == "ollama", (
            f"Expected ollama to lead when keys missing, got {local_fast_candidates[0].name}"
        )
        assert local_only_router.select_provider("fast_chat").config.adapter == "ollama"
        print("  -> PASSED: Zero-cost offline fallback promoted Ollama to top rank when keys are absent!")

    finally:
        for k, v in env_backup.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)


# ==============================================================================
# TEST 3: EWMA Latency Updates on Successful Responses
# ==============================================================================
async def test_ewma_latency_updates():
    print("[TEST 3] Testing EWMA Latency updates (formula precision & execution hook)...")

    # 3.1 Mathematical verification of ProviderMetrics
    metrics = ProviderMetrics(default_latency_ms=300.0, alpha=0.25)
    assert metrics.ewma_latency_ms == 300.0
    assert metrics.total_requests == 0
    assert metrics.successful_requests == 0
    assert metrics.failed_requests == 0

    # Step 1: Success with 100ms
    # S_1 = 0.25 * 100.0 + 0.75 * 300.0 = 25.0 + 225.0 = 250.0
    metrics.update_success(100.0)
    assert abs(metrics.ewma_latency_ms - 250.0) < 1e-5, f"Expected 250.0, got {metrics.ewma_latency_ms}"
    assert metrics.total_requests == 1
    assert metrics.successful_requests == 1

    # Step 2: Success with 50ms
    # S_2 = 0.25 * 50.0 + 0.75 * 250.0 = 12.5 + 187.5 = 200.0
    metrics.update_success(50.0)
    assert abs(metrics.ewma_latency_ms - 200.0) < 1e-5, f"Expected 200.0, got {metrics.ewma_latency_ms}"
    assert metrics.total_requests == 2
    assert metrics.successful_requests == 2

    # Step 3: Failure penalty (multiplier 1.5)
    # S_3 = 200.0 * 1.5 = 300.0
    metrics.update_failure()
    assert abs(metrics.ewma_latency_ms - 300.0) < 1e-5, f"Expected 300.0, got {metrics.ewma_latency_ms}"
    assert metrics.total_requests == 3
    assert metrics.failed_requests == 1
    print("  -> PASSED: ProviderMetrics EWMA math & penalty multiplier strictly verified!")

    # 3.2 Runtime verification in router.execute_with_fallback()
    os.environ["GROQ_API_KEY"] = "mock_groq_key"
    try:
        router = ParetoRouter()
        initial_groq_ewma = router._metrics["groq"].ewma_latency_ms

        mock_resp = ProviderResponse(
            content="Fast chat response",
            model="llama-3.3-70b-versatile",
            latency_ms=80.0,
        )

        with patch.object(router._providers["groq"], "generate", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_resp
            resp = await router.execute_with_fallback(
                task="fast_chat",
                messages=[Message(role="user", content="Ping")],
            )
            assert resp.content == "Fast chat response"
            assert router._metrics["groq"].successful_requests == 1
            assert router._metrics["groq"].ewma_latency_ms != initial_groq_ewma
            print(
                f"  -> PASSED: Runtime EWMA updated on success: "
                f"{initial_groq_ewma:.1f}ms -> {router._metrics['groq'].ewma_latency_ms:.1f}ms"
            )
    finally:
        os.environ.pop("GROQ_API_KEY", None)


# ==============================================================================
# TEST 4: Automatic Fallback Along Task Cascade
# ==============================================================================
async def test_automatic_cascade_fallback():
    print("[TEST 4] Testing automatic fallback along task cascade on failure & tripped breaker...")

    os.environ["GROQ_API_KEY"] = "mock_groq_key"
    os.environ["GEMINI_API_KEY"] = "mock_gemini_key"
    os.environ["OPENROUTER_API_KEY"] = "mock_openrouter_key"

    try:
        # 4.1 Primary provider throws error -> Cascade to secondary provider
        router = ParetoRouter()
        groq_provider = router._providers["groq"]
        gemini_provider = router._providers["gemini"]

        mock_gemini_resp = ProviderResponse(
            content="Fallback Gemini response",
            model="gemini-2.5-flash",
            latency_ms=110.0,
        )

        with patch.object(groq_provider, "generate", new_callable=AsyncMock) as mock_groq_gen, \
             patch.object(gemini_provider, "generate", new_callable=AsyncMock) as mock_gemini_gen:

            # Groq fails with 429 Too Many Requests
            mock_groq_gen.side_effect = RuntimeError("Groq HTTP 429: Rate Limit Exceeded")
            mock_gemini_gen.return_value = mock_gemini_resp

            resp = await router.execute_with_fallback(
                task="fast_chat",
                messages=[Message(role="user", content="Hello")],
            )

            assert resp.content == "Fallback Gemini response"
            assert resp.model == "gemini-2.5-flash"
            assert router._metrics["groq"].failed_requests == 1
            assert router._metrics["gemini"].successful_requests == 1
            print("  -> PASSED: Failover from failing Groq (429) to Gemini succeeded smoothly!")

        # 4.2 Tripped Circuit Breaker pre-check fallback
        # Trip Groq's circuit breaker to OPEN
        cb = groq_provider.circuit_breaker
        for _ in range(cb.max_failures):
            await cb.record_failure(RuntimeError("Service unavailable"))
        assert cb.state == CircuitState.OPEN
        assert groq_provider.is_available is False

        # Verify candidate ranking immediately demotes groq behind available providers
        ranked = router.get_ranked_candidates("fast_chat")
        assert ranked[0].name == "gemini"
        assert ranked[-1].name == "groq"
        assert ranked[-1].is_available is False

        # Execute call: Groq should be skipped entirely, routing directly to Gemini
        with patch.object(groq_provider, "generate", new_callable=AsyncMock) as mock_groq_gen, \
             patch.object(gemini_provider, "generate", new_callable=AsyncMock) as mock_gemini_gen:

            mock_gemini_gen.return_value = mock_gemini_resp
            resp = await router.execute_with_fallback(
                task="fast_chat",
                messages=[Message(role="user", content="Next message")],
            )

            assert resp.model == "gemini-2.5-flash"
            # Groq's generate was not even attempted because breaker is OPEN
            mock_groq_gen.assert_not_called()
            mock_gemini_gen.assert_called_once()
            print("  -> PASSED: Provider with OPEN circuit breaker was bypassed without invocation!")

        # 4.3 Multi-hop cascade down to tertiary provider
        router_multi = ParetoRouter()
        p_groq = router_multi._providers["groq"]
        p_gemini = router_multi._providers["gemini"]
        p_openrouter = router_multi._providers["openrouter_free"]

        mock_or_resp = ProviderResponse(
            content="Tertiary OpenRouter response",
            model="meta-llama/llama-3.3-70b-instruct:free",
        )

        with patch.object(p_groq, "generate", new_callable=AsyncMock) as mock_g, \
             patch.object(p_gemini, "generate", new_callable=AsyncMock) as mock_gem, \
             patch.object(p_openrouter, "generate", new_callable=AsyncMock) as mock_or:

            mock_g.side_effect = RuntimeError("Groq down")
            mock_gem.side_effect = RuntimeError("Gemini down")
            mock_or.return_value = mock_or_resp

            resp = await router_multi.execute_with_fallback(
                task="fast_chat",
                messages=[Message(role="user", content="Deep query")],
            )

            assert resp.content == "Tertiary OpenRouter response"
            assert router_multi._metrics["groq"].failed_requests == 1
            assert router_multi._metrics["gemini"].failed_requests == 1
            assert router_multi._metrics["openrouter_free"].successful_requests == 1
            print("  -> PASSED: Multi-hop cascade (groq -> gemini -> openrouter_free) verified!")

        # 4.4 Complete cascade exhaustion
        router_exhaust = ParetoRouter()
        for p in router_exhaust._providers.values():
            p.generate = AsyncMock(side_effect=RuntimeError("All endpoints down"))

        exhausted_caught = False
        try:
            await router_exhaust.execute_with_fallback(
                task="fast_chat",
                messages=[Message(role="user", content="Fail query")],
            )
        except RuntimeError as re:
            exhausted_caught = True
            assert "All providers exhausted for task cascade 'fast_chat'" in str(re)
            print(f"  -> PASSED: Cascade exhaustion correctly raised RuntimeError: {re}")

        assert exhausted_caught is True

    finally:
        os.environ.pop("GROQ_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("OPENROUTER_API_KEY", None)


# ==============================================================================
# MAIN TEST RUNNER
# ==============================================================================
async def main():
    print("=" * 60)
    print("RUNNING LIVE VERIFICATION: makima/provider/router.py (ParetoRouter)")
    print("=" * 60)
    await test_ollama_discovery()
    await test_candidate_ranking_pareto_frontier()
    await test_ewma_latency_updates()
    await test_automatic_cascade_fallback()
    print("=" * 60)
    print("ALL PARETOROUTER VERIFICATION CHECKS PASSED! (EXIT CODE 0)")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
