"""
Makima v2 — Hermes Core Agent Brain.
Exports:
  - HermesAgentEngine: Autonomous while-loop with tool calling & Pareto routing
  - ContextCompressor: Dynamic middle-turn token compressor preserving Head and Tail
  - Guardrails: Dangerous command blocker and Shannon entropy secret redactor
  - StructuredTelemetry: Lightweight in-process event emitter with JSONL persistence
"""

from makima.core.context import (
    ContextCompressor,
    TokenCounter,
    count_tokens,
)
from makima.core.engine import (
    EngineResult,
    HermesAgentEngine,
)
from makima.core.guardrails import (
    DangerousCommandError,
    Guardrails,
    GuardrailViolationError,
    SecretLeakError,
    filter_secrets,
)
from makima.core.telemetry import (
    StructuredTelemetry,
    TelemetryEvent,
    get_telemetry,
)

__all__ = [
    "HermesAgentEngine",
    "EngineResult",
    "ContextCompressor",
    "TokenCounter",
    "count_tokens",
    "Guardrails",
    "DangerousCommandError",
    "SecretLeakError",
    "GuardrailViolationError",
    "filter_secrets",
    "StructuredTelemetry",
    "TelemetryEvent",
    "get_telemetry",
]
