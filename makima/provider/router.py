"""
Makima v2 — Dynamic Zero-Cost ParetoRouter.
Architectural Pattern: Multi-criteria Pareto Frontier Selection with Task Cascades and Jittered Fallback.
Zero-Hardcoding Guarantee: Dynamically probes env keys and local Ollama daemon (/api/tags).
Zero-Cost Policy: Exclusively routes through free-tier quotas and 100% offline local models.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple


from makima.config import BackendConfig, MakimaSettings, get_settings
from makima.provider.adapters.base import BaseProvider, Message, ProviderResponse
from makima.provider.adapters.gemini import GeminiProvider
from makima.provider.adapters.openai_compatible import OpenAICompatibleProvider
from makima.provider.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

logger = logging.getLogger("makima.provider.router")


class ProviderMetrics:
    """Tracks runtime performance metrics including Exponentially Weighted Moving Average (EWMA) latency."""

    def __init__(self, default_latency_ms: float = 300.0, alpha: float = 0.25):
        self.ewma_latency_ms: float = default_latency_ms
        self.alpha: float = alpha
        self.total_requests: int = 0
        self.successful_requests: int = 0
        self.failed_requests: int = 0
        self.last_used: float = 0.0

    def update_success(self, latency_ms: float) -> None:
        self.total_requests += 1
        self.successful_requests += 1
        self.last_used = time.monotonic()
        # EWMA latency update: S_t = alpha * Y_t + (1 - alpha) * S_{t-1}
        self.ewma_latency_ms = (self.alpha * latency_ms) + ((1.0 - self.alpha) * self.ewma_latency_ms)

    def update_failure(self) -> None:
        self.total_requests += 1
        self.failed_requests += 1
        self.last_used = time.monotonic()
        # Penalty multiplier on failure
        self.ewma_latency_ms *= 1.5


class ParetoCandidate:
    """Represents a candidate provider evaluated along multi-dimensional Pareto criteria."""

    def __init__(
        self,
        name: str,
        provider: BaseProvider,
        cascade_rank: int,
        latency_tier_score: int,
        ewma_ms: float,
        failure_count: int,
        is_available: bool,
    ):
        self.name = name
        self.provider = provider
        self.cascade_rank = cascade_rank
        self.latency_tier_score = latency_tier_score
        self.ewma_ms = ewma_ms
        self.failure_count = failure_count
        self.is_available = is_available

    @property
    def sort_key(self) -> Tuple[int, int, int, int, int]:
        """
        Pareto Sort Tuple:
          1. Availability: 0 (Available) < 1 (Unavailable / Circuit Open)
          2. Health Penalty: 0 (0 consecutive failures) < 1 (active failures demoted)
          3. Cascade Preference: Configured task cascade rank for healthy models
          4. EWMA Latency: Bucketed latency
          5. Failure Count: Total consecutive failures
        """
        return (
            0 if self.is_available else 1,
            1 if self.failure_count > 0 else 0,
            self.cascade_rank,
            int(round(self.ewma_ms / 50.0)),
            self.failure_count,
        )


class ParetoRouter:
    """
    Intelligent zero-cost model router for Makima v2.
    Routes tasks (fast_chat, code, deep_reasoning, vision, offline) to optimal free backends.
    """

    LATENCY_SCORES = {
        "fast": 1,
        "standard": 2,
        "slow": 3,
    }

    def __init__(
        self,
        settings: Optional[MakimaSettings] = None,
        *,
        strict_local_availability: bool = False,
    ):
        self.settings = settings or get_settings()
        self.strict_local_availability = strict_local_availability
        self._providers: Dict[str, BaseProvider] = {}
        self._metrics: Dict[str, ProviderMetrics] = {}
        self._ollama_probed_models: List[str] = []
        self._initialized = False
        self._lock = asyncio.Lock()
        self._register_backends()

    @property
    def ollama_probed_models(self) -> List[str]:
        """Returns discovered models from local Ollama daemon."""
        return self._ollama_probed_models

    def _register_backends(self) -> None:
        """Dynamically registers configured backends and baseline metrics."""
        for name, config in self.settings.providers.backends.items():
            if name not in self._providers:
                provider = self._create_provider(name, config)
                self._providers[name] = provider

                default_latency = 100.0 if config.latency_tier == "fast" else 400.0
                self._metrics[name] = ProviderMetrics(default_latency_ms=default_latency)

    def _create_provider(self, name: str, config: BackendConfig) -> BaseProvider:
        """Instantiates the appropriate strategy adapter for a configured backend."""
        cb_conf = self.settings.providers.circuit_breaker
        circuit_breaker = CircuitBreaker(
            name=name,
            max_failures=cb_conf.max_failures,
            cooldown_seconds=cb_conf.cooldown_seconds,
            jitter=cb_conf.jitter,
        )

        if config.adapter == "gemini":
            return GeminiProvider(config=config, circuit_breaker=circuit_breaker)
        elif config.adapter in ("openai", "ollama"):
            return OpenAICompatibleProvider(config=config, circuit_breaker=circuit_breaker)
        else:
            raise ValueError(f"Unsupported adapter type '{config.adapter}' for backend '{name}'")

    async def initialize(self) -> None:
        """Dynamically registers configured backends and probes the local Ollama daemon."""
        async with self._lock:
            if self._initialized:
                return

            self._register_backends()
            # Probe local Ollama if available
            await self.probe_ollama()
            self._initialized = True

    async def probe_ollama(self) -> List[str]:
        """Probes Ollama daemon on localhost:11434 to discover active offline models."""
        ollama_cfg = self.settings.get_backend("ollama")
        base_url = ollama_cfg.base_url if ollama_cfg and ollama_cfg.base_url else "http://localhost:11434"
        tags_url = f"{base_url.rstrip('/')}/api/tags"

        try:
            from makima.core.http_pool import get_shared_client
            client = await get_shared_client()
            resp = await client.get(tags_url, timeout=1.5)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                self._ollama_probed_models = models
                logger.info(f"Discovered local Ollama models: {models}")
                return models
        except Exception as e:
            logger.debug(f"Ollama daemon not reachable at {tags_url}: {e}")

        self._ollama_probed_models = []
        return []

    def get_ranked_candidates(self, task: str = "fast_chat") -> List[ParetoCandidate]:
        """
        Evaluates and ranks all candidates for a specific task cascade using Pareto criteria.
        """
        cascade = self.settings.providers.cascades.get(task, [])
        if not cascade:
            # Fallback to all configured backends
            cascade = list(self.settings.providers.backends.keys())

        candidates: List[ParetoCandidate] = []
        for rank, name in enumerate(cascade):
            provider = self._providers.get(name)
            if not provider:
                continue

            config = provider.config
            metrics = self._metrics.get(name, ProviderMetrics())
            tier_score = self.LATENCY_SCORES.get(config.latency_tier, 2)
            is_avail = provider.is_available
            # BackendConfig treats Ollama as keyless/available. Benchmark
            # runs need a stricter interpretation after the daemon probe,
            # otherwise a dead local endpoint is selected first.
            if (
                self.strict_local_availability
                and name == "ollama"
                and not self._ollama_probed_models
            ):
                is_avail = False

            candidate = ParetoCandidate(
                name=name,
                provider=provider,
                cascade_rank=rank,
                latency_tier_score=tier_score,
                ewma_ms=metrics.ewma_latency_ms,
                failure_count=provider.circuit_breaker.consecutive_failures,
                is_available=is_avail,
            )
            candidates.append(candidate)

        # Sort candidates along Pareto frontier
        candidates.sort(key=lambda c: c.sort_key)
        return candidates

    def select_provider(self, task: str = "fast_chat") -> BaseProvider:
        """Returns the optimal available provider for the given task."""
        candidates = self.get_ranked_candidates(task)
        for c in candidates:
            if c.is_available:
                return c.provider

        # If all candidates in cascade are unavailable, pick the first configured provider as last resort
        if candidates:
            return candidates[0].provider

        raise RuntimeError(f"No providers configured or available for task '{task}'.")

    async def execute_with_fallback(
        self,
        task: str,
        messages: List[Message],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        preferred_backend: Optional[str] = None,
        **kwargs,
    ) -> ProviderResponse:
        """
        Dispatches request along the Pareto frontier cascade with automatic failover.
        If a provider encounters a rate limit (429) or connection error, the circuit breaker trips
        and the router seamlessly falls back to the next free backend.
        """
        if not self._initialized:
            await self.initialize()

        candidates = self.get_ranked_candidates(task)
        if not candidates:
            raise RuntimeError(f"No provider candidates found for task '{task}'.")

        # A UI-selected backend is a preference, not a bypass of availability
        # and fallback policy. Move it to the front when it belongs to the
        # configured cascade; the normal circuit-breaker fallback remains intact.
        if preferred_backend:
            preferred = next((c for c in candidates if c.name == preferred_backend), None)
            if preferred is not None:
                candidates = [preferred] + [c for c in candidates if c is not preferred]
            elif preferred_backend in self._providers:
                prov = self._providers[preferred_backend]
                if prov.is_available:
                    pref_cand = ParetoCandidate(
                        name=preferred_backend,
                        provider=prov,
                        cascade_rank=-1,
                        latency_tier_score=self.LATENCY_SCORES.get(prov.config.latency_tier, 2),
                        ewma_ms=self._metrics.get(preferred_backend, ProviderMetrics()).ewma_latency_ms,
                        failure_count=prov.circuit_breaker.consecutive_failures,
                        is_available=True,
                    )
                    candidates = [pref_cand] + candidates

        # Append any additional available configured backends not already in the task cascade
        # so 403 FreeTierOnly / 429 on one model seamlessly fails over to other active free models.
        seen_names = {c.name for c in candidates}
        extra_available: List[ParetoCandidate] = []
        for rank_idx, (b_name, b_prov) in enumerate(self._providers.items(), start=len(candidates)):
            if b_name not in seen_names and b_prov.is_available:
                extra_available.append(
                    ParetoCandidate(
                        name=b_name,
                        provider=b_prov,
                        cascade_rank=rank_idx,
                        latency_tier_score=self.LATENCY_SCORES.get(b_prov.config.latency_tier, 2),
                        ewma_ms=self._metrics.get(b_name, ProviderMetrics()).ewma_latency_ms,
                        failure_count=b_prov.circuit_breaker.consecutive_failures,
                        is_available=True,
                    )
                )
                seen_names.add(b_name)

        # If local Ollama was probed during initialize() and is offline (no local models found),
        # place extra available cloud backends BEFORE offline ollama so requests don't hit a closed port first.
        if self._initialized and not self._ollama_probed_models and task != "offline" and preferred_backend != "ollama":
            non_ollama = [c for c in candidates if c.name != "ollama"]
            ollama_only = [c for c in candidates if c.name == "ollama"]
            candidates = non_ollama + extra_available + ollama_only
        else:
            candidates = candidates + extra_available

        # Re-apply preferred_backend pin to the very front if requested
        if preferred_backend:
            preferred = next((c for c in candidates if c.name == preferred_backend), None)
            if preferred is not None:
                candidates = [preferred] + [c for c in candidates if c is not preferred]

        last_error: Optional[Exception] = None
        cloud_error: Optional[Exception] = None

        for candidate in candidates:
            provider = candidate.provider
            backend_name = candidate.name
            metrics = self._metrics.get(backend_name)

            if not provider.is_available:
                continue

            # If local Ollama was already probed during initialize() and found offline (0 models),
            # skip hitting localhost:11434 when we already have other candidates or cloud errors.
            if (
                backend_name == "ollama"
                and self._initialized
                and not self._ollama_probed_models
                and len(candidates) > 1
                and cloud_error is not None
            ):
                logger.debug("Skipping unprobed/offline local Ollama daemon after cloud error.")
                continue

            try:
                start_time = time.monotonic()
                response = await provider.generate(
                    messages=messages,
                    system_prompt=system_prompt,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                elapsed_ms = (time.monotonic() - start_time) * 1000.0

                if metrics:
                    metrics.update_success(elapsed_ms)

                return response

            except CircuitBreakerOpenError as cbe:
                logger.warning(f"Provider '{backend_name}' circuit breaker is open: {cbe}. Cascading to next candidate.")
                last_error = cbe
                if backend_name != "ollama":
                    cloud_error = cbe
                continue
            except Exception as e:
                logger.warning(f"Provider '{backend_name}' failed with {type(e).__name__}: {e}. Cascading.")
                if metrics:
                    metrics.update_failure()
                last_error = e
                if backend_name != "ollama":
                    cloud_error = e
                continue

        effective_error = cloud_error or last_error
        raise RuntimeError(
            f"All providers exhausted for task cascade '{task}'. Last error: {effective_error}"
        )

    async def close(self) -> None:
        """Gracefully closes underlying provider clients and resources."""
        for name, provider in self._providers.items():
            try:
                if hasattr(provider, "close"):
                    res = provider.close()
                    if asyncio.iscoroutine(res):
                        await res
                elif hasattr(provider, "_client") and provider._client is not None:
                    if hasattr(provider._client, "close"):
                        res = provider._client.close()
                        if asyncio.iscoroutine(res):
                            await res
            except Exception as e:
                logger.debug(f"Error closing provider '{name}': {e}")

