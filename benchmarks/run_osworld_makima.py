"""Run one Makima-owned benchmark task against the configured backend."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any


def _official_osworld_runtime_available() -> bool:
    """Return whether the official OSWorld evaluator is available locally."""
    osworld_root = os.getenv("OSWORLD_ROOT") or str(
        Path(__file__).resolve().parents[1] / "third_party" / "OSWorld"
    )
    return bool(
        Path(osworld_root, "desktop_env").is_dir()
        and Path(osworld_root, "lib_run_single.py").is_file()
    ) or importlib.util.find_spec("desktop_env") is not None


def _daytona_preflight() -> tuple[bool, dict[str, Any]]:
    """Verify that the selected Daytona sandbox can execute commands."""
    if not os.getenv("DAYTONA_API_KEY"):
        return False, {"error": "DAYTONA_API_KEY is not configured."}

    try:
        from daytona import Daytona, DaytonaConfig  # type: ignore

        config = DaytonaConfig(
            api_key=os.getenv("DAYTONA_API_KEY"),
            api_url=os.getenv("DAYTONA_API_URL", "https://app.daytona.io/api"),
        )
        client = Daytona(config)
        sandboxes = list(client.list())
        if not sandboxes:
            return False, {"error": "No Daytona sandbox is available."}

        sandbox_id = os.getenv("DAYTONA_SANDBOX_ID")
        sandbox = client.get(sandbox_id) if sandbox_id else sandboxes[0]
        response = sandbox.process.exec("printf makima-daytona-preflight", timeout=15)
        output = str(getattr(response, "result", response)).strip()
        if "makima-daytona-preflight" not in output:
            return False, {"error": "Daytona process bridge returned an unexpected response."}
        return True, {"sandbox_count": len(sandboxes), "process_bridge": True}
    except Exception as exc:
        return False, {
            "error": f"Daytona sandbox process preflight failed: {type(exc).__name__}: {exc}",
            "hint": "Verify DAYTONA_SANDBOX_ID and that the sandbox is started with the OSWorld VM/GUI bridge.",
        }
from pathlib import Path

from benchmarks.osworld_makima import MakimaOSWorldAgent
from makima.core.engine import HermesAgentEngine
from makima.provider.router import ParetoRouter
from makima.tools.registry import get_registry


async def _run(args: argparse.Namespace) -> int:
    if args.runtime == "daytona" and not os.getenv("DAYTONA_API_KEY"):
        print(json.dumps({
            "benchmark": "Run Continuous",
            "suite": "OSWorld",
            "runtime": "daytona",
            "task_id": args.task_id,
            "agent_name": "Makima",
            "completed": False,
            "error": "DAYTONA_API_KEY is not configured; Daytona VM benchmark cannot start.",
            "hint": "Configure Daytona credentials and VM/GUI bridge, or pass --runtime local for a host smoke test.",
            "max_steps": args.max_steps,
        }, ensure_ascii=True, indent=2))
        return 2

    if args.runtime == "daytona":
        ready, details = _daytona_preflight()
        if not ready:
            print(json.dumps({
                "benchmark": "Run Continuous",
                "suite": "OSWorld",
                "runtime": "Daytona",
                "task_id": args.task_id,
                "agent_name": "Makima",
                "completed": False,
                "max_steps": args.max_steps,
                **details,
            }, ensure_ascii=True, indent=2))
            return 2

    registry = get_registry(auto_discover=True)
    agent = MakimaOSWorldAgent(
        HermesAgentEngine(
            router=ParetoRouter(strict_local_availability=True),
            enable_implicit_learning=False,
        ),
        registry,
        task_cascade=args.task_cascade,
        max_turns=args.max_steps,
    )
    observation = {}
    if args.observation:
        observation = json.loads(Path(args.observation).read_text(encoding="utf-8"))
    try:
        result = await agent.run_task(
            args.instruction,
            task_id=args.task_id,
            observation=observation,
        )
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        hint = None
        if "invalid_api_key" in error_text or "AuthenticationError" in error_text:
            hint = (
                "Check DASHSCOPE_API_KEY and ensure it belongs to the region used by "
                "the configured DashScope base URL."
            )
        elif "FreeTierOnly" in error_text or "free quota" in error_text.lower():
            hint = (
                "DashScope reached its free-tier quota. Enable paid usage or choose "
                "an account/model with remaining quota before rerunning."
            )
        print(json.dumps({
            "task_id": args.task_id,
            "benchmark": "Run Continuous",
            "suite": "OSWorld",
            "runtime": args.runtime,
            "agent_name": "Makima",
            "reasoning_backend": None,
            "completed": False,
            "error": error_text,
            "hint": hint,
            "max_steps": args.max_steps,
        }, ensure_ascii=True, indent=2))
        return 2
    payload = result.to_dict()
    payload.update({
        "benchmark": "Run Continuous",
        "suite": "OSWorld",
        "runtime": args.runtime,
        "max_steps": args.max_steps,
    })
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.completed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an OSWorld task through Makima.")
    parser.add_argument("instruction")
    parser.add_argument("--task-id", default="local-task")
    parser.add_argument("--observation", help="JSON observation metadata file")
    parser.add_argument("--task-cascade", default="osworld")
    parser.add_argument("--runtime", choices=("daytona", "local"), default="daytona")
    parser.add_argument("--max-steps", type=int, choices=(15, 20), default=15)
    parser.add_argument("--continuous", action="store_true", help="Repeat the Daytona task until failure or Ctrl+C")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between continuous runs")
    parser.add_argument(
        "--max-turns",
        dest="max_steps",
        type=int,
        choices=(15, 20),
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if not args.continuous:
        return asyncio.run(_run(args))

    iteration = 0
    try:
        while True:
            iteration += 1
            print(f"[Daytona continuous run {iteration}]", flush=True)
            exit_code = asyncio.run(_run(args))
            if exit_code != 0:
                return exit_code
            time.sleep(max(0.0, args.interval))
    except KeyboardInterrupt:
        print("Daytona continuous run stopped by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
