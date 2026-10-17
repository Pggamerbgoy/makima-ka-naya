"""Run Makima against the bounded Windows OSWorld-inspired benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json

from benchmarks.windows_safe_osworld import (
    SAFE_TASKS,
    SafeWindowsBenchmark,
    build_safe_registry,
)
from makima.core.engine import HermesAgentEngine
from makima.provider.router import ParetoRouter


SAFE_SYSTEM_PROMPT = """You are Makima under a bounded Windows OSWorld-inspired benchmark.
The task has already been reset into a disposable workspace owned by the harness.
Use only the explicitly provided allowlisted tools. Inspect before writing,
write only the expected output files, run evaluate_task before finishing, and
never invent tools. Never delete, kill, shell out, browse, message, change
settings, or access a path outside the benchmark workspace.
"""


async def run(task_id: str = "windows-files-001", max_steps: int = 15) -> dict:
    harness = SafeWindowsBenchmark(task_id=task_id)
    registry = build_safe_registry(harness)
    setup = harness.prepare_task()
    result = None
    error = None
    try:
        engine = HermesAgentEngine(
            router=ParetoRouter(strict_local_availability=True),
            enable_implicit_learning=False,
        )
        try:
            result = await engine.run(
                prompt=harness.task.instruction,
                system_prompt=SAFE_SYSTEM_PROMPT,
                tools=registry,
                task="osworld",
                max_turns=max_steps,
                session_id=f"windows-safe-osworld-{task_id}",
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        evaluation = harness.evaluate_task()
        payload = {
            "benchmark": "Makima Windows Safe OSWorld-inspired",
            "agent_name": "Makima",
            "runtime": "Windows host / disposable workspace",
            "task_id": task_id,
            "task_title": harness.task.title,
            "official_osworld_score": False,
            "completed": bool(result and result.completed and evaluation["passed"]),
            "error": error,
            "reasoning_backend": getattr(result, "model_used", "") if result else "",
            "turn_count": getattr(result, "turn_count", 0) if result else 0,
            "tool_calls_executed": getattr(result, "tool_calls_executed", 0) if result else 0,
            "finish_reason": getattr(result, "finish_reason", "error") if result else "error",
            "setup": setup,
            "evaluation": evaluation,
            "trajectory": harness.events,
            "allowed_tools": registry.list_names(),
            "content": getattr(result, "content", "") if result else "",
        }
        return payload
    finally:
        harness.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a safe, hard OSWorld-inspired Windows task through Makima.")
    parser.add_argument("--task-id", choices=tuple(SAFE_TASKS), default="windows-files-001")
    parser.add_argument("--max-steps", type=int, choices=range(1, 21), default=15)
    parser.add_argument("--list-tasks", action="store_true")
    args = parser.parse_args()
    if args.list_tasks:
        print(json.dumps([{"task_id": task.task_id, "title": task.title} for task in SAFE_TASKS.values()], indent=2))
        return 0
    payload = asyncio.run(run(task_id=args.task_id, max_steps=args.max_steps))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
