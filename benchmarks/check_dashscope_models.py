"""Probe each configured Alibaba model without running an OSWorld task."""

from __future__ import annotations

import asyncio
import argparse
import time

from makima.config import get_settings
from makima.provider.adapters.base import Message
from makima.provider.adapters.openai_compatible import OpenAICompatibleProvider
from makima.provider.circuit_breaker import CircuitBreaker


def _console_safe(value: str, limit: int = 180) -> str:
    return value.replace("\n", " ").encode("ascii", "backslashreplace").decode("ascii")[:limit]


async def main(selected_names: list[str] | None = None) -> int:
    settings = get_settings(force_reload=True)
    names = selected_names or settings.providers.cascades.get("osworld", [])
    responded = 0

    print("DashScope model availability probe")
    print("=" * 36)
    for name in names:
        config = settings.get_backend(name)
        if config is None:
            print(f"{name}: CONFIG_MISSING")
            continue

        provider = OpenAICompatibleProvider(
            config=config,
            circuit_breaker=CircuitBreaker(name=name, max_failures=1, cooldown_seconds=1, jitter=False),
        )
        started = time.perf_counter()
        try:
            response = await provider.generate(
                messages=[Message(role="user", content="Reply with OK only.")],
                temperature=0,
                max_tokens=8,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            content = _console_safe((response.content or "").strip(), 80)
            print(f"{name} | {config.model} | RESPONDED | {elapsed_ms} ms | {content!r}")
            responded += 1
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            error = _console_safe(str(exc))
            print(f"{name} | {config.model} | UNAVAILABLE | {elapsed_ms} ms | {type(exc).__name__}: {error}")

    print("=" * 36)
    print(f"responding_models={responded}/{len(names)}")
    return 0 if responded else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", help="Configured backend names to probe")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.models)))
