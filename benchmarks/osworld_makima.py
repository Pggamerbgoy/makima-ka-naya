"""OSWorld/Daytona adapter that evaluates Makima, not its LLM backend.

The important boundary here is deliberate:

    OSWorld task -> MakimaOSWorldAgent -> HermesAgentEngine
                                      -> Alibaba/Qwen/etc. backend
                                      -> Makima ToolRegistry / VM tools

The model name is recorded as ``reasoning_backend`` only.  ``agent_name``
always remains ``Makima`` so result files cannot accidentally attribute an
end-to-end Makima run to the provider used inside Makima.

This module does not import the Daytona SDK at module import time.  Daytona is
an optional dependency and the local contract tests must work without network
credentials or a live sandbox.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional

from makima.core.engine import EngineResult, HermesAgentEngine
from makima.tools.registry import ToolRegistry


OSWORLD_SYSTEM_PROMPT = """You are Makima, the end-to-end computer-use agent under evaluation.
The language model selected by the provider router is only Makima's internal reasoning backend.
Do not identify the backend as the agent. Use Makima's
registered tools to inspect and operate the benchmark environment, and finish
the requested OSWorld task before giving a final response.
"""


def _observation_context(observation: Optional[Mapping[str, Any]]) -> str:
    """Serialize observation metadata without embedding binary screenshots."""
    if not observation:
        return "No external observation was supplied; use Makima tools to inspect the VM."

    safe: Dict[str, Any] = {}
    for key, value in observation.items():
        if isinstance(value, (bytes, bytearray, memoryview)):
            safe[key] = f"<binary observation: {len(value)} bytes>"
        elif isinstance(value, str) and len(value) > 4000:
            safe[key] = value[:4000] + "...<truncated>"
        else:
            safe[key] = value
    return "OSWorld observation metadata:\n" + json.dumps(safe, ensure_ascii=False, default=str)


@dataclass(frozen=True)
class OSWorldRun:
    """Auditable result record with separate agent and backend identities."""

    task_id: str
    agent_name: str
    reasoning_backend: str
    completed: bool
    turn_count: int
    tool_calls_executed: int
    content: str
    finish_reason: str
    latency_ms: float
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_engine_result(
        cls,
        task_id: str,
        result: EngineResult,
        *,
        agent_name: str = "Makima",
    ) -> "OSWorldRun":
        return cls(
            task_id=task_id,
            agent_name=agent_name,
            reasoning_backend=result.model_used,
            completed=result.completed,
            turn_count=result.turn_count,
            tool_calls_executed=result.tool_calls_executed,
            content=result.content,
            finish_reason=result.finish_reason,
            latency_ms=result.latency_ms,
            error=result.error,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MakimaOSWorldAgent:
    """Makima-owned OSWorld entrypoint.

    ``run_task`` is the Daytona/Makima integration path: Makima's engine gets
    the task, observation context, and ToolRegistry, then executes tools in the
    VM-facing process. ``predict`` is provided for OSWorld's standard agent
    shape and returns a JSON-safe final response for harness integrations that
    expect that method.
    """

    agent_name = "Makima"

    def __init__(
        self,
        engine: HermesAgentEngine,
        registry: ToolRegistry,
        *,
        task_cascade: Optional[str] = None,
        max_turns: int = 15,
    ) -> None:
        self.engine = engine
        self.registry = registry
        if task_cascade is None:
            try:
                from makima.config import get_settings
                s = get_settings()
                task_cascade = "osworld" if "osworld" in s.providers.cascades else "fast_chat"
            except Exception:
                task_cascade = "osworld"
        self.task_cascade = task_cascade
        self.max_turns = max_turns
        self._last_run: Optional[OSWorldRun] = None

    def reset(self) -> None:
        """Reset per-task state; provider/router state remains owned by Makima."""
        self._last_run = None

    async def run_task(
        self,
        instruction: str,
        *,
        task_id: str = "local-task",
        observation: Optional[Mapping[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> OSWorldRun:
        if not instruction or not instruction.strip():
            raise ValueError("OSWorld task instruction must not be empty.")

        prompt = f"OSWorld task instruction:\n{instruction.strip()}\n\n{_observation_context(observation)}"
        result = await self.engine.run(
            prompt=prompt,
            system_prompt=OSWORLD_SYSTEM_PROMPT,
            tools=self.registry,
            task=self.task_cascade,
            max_turns=self.max_turns,
            session_id=session_id or f"osworld:{task_id}",
        )
        run = OSWorldRun.from_engine_result(task_id, result, agent_name=self.agent_name)
        self._last_run = run
        return run

    def predict(
        self,
        instruction: str,
        observation: Optional[Mapping[str, Any]] = None,
        *,
        task_id: str = "local-task",
    ) -> Dict[str, Any]:
        """Synchronous OSWorld-shaped adapter for simple runners."""
        run = asyncio.run(self.run_task(instruction, task_id=task_id, observation=observation))
        return {
            "agent_name": run.agent_name,
            "reasoning_backend": run.reasoning_backend,
            "completed": run.completed,
            "content": run.content,
            "tool_calls_executed": run.tool_calls_executed,
            "finish_reason": run.finish_reason,
        }


class DaytonaRuntime:
    """Small optional Daytona lifecycle wrapper for benchmark preflight/setup."""

    def __init__(self, daytona_client: Any = None, sandbox: Any = None) -> None:
        self.client = daytona_client
        self.sandbox = sandbox

    def create(self, **kwargs: Any) -> Any:
        if self.client is None:
            try:
                from daytona import Daytona  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "Daytona is optional. Install the sandboxing extra before using DaytonaRuntime."
                ) from exc
            self.client = Daytona()
        self.sandbox = self.client.create(**kwargs)
        return self.sandbox

    def exec(self, command: str, *, cwd: Optional[str] = None, timeout: Optional[int] = None) -> str:
        if self.sandbox is None:
            raise RuntimeError("Create a Daytona sandbox before executing commands.")
        response = self.sandbox.process.exec(command, cwd=cwd, timeout=timeout)
        return str(getattr(response, "result", response))

    def close(self) -> None:
        if self.sandbox is None:
            return
        delete = getattr(self.sandbox, "delete", None)
        if callable(delete):
            delete()
        self.sandbox = None
