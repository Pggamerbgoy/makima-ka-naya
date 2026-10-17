"""A destructive-action-free, OSWorld-inspired benchmark for Windows.

This is intentionally *not* an official OSWorld score. It keeps the shape of
the official loop (task setup, observation/tool loop, executable evaluator)
while replacing the VM desktop with a disposable, harness-owned workspace.
Only fixed files inside that workspace may be read or written, and the only
optional process is the Notepad child opened by this harness.
"""

from __future__ import annotations

import csv
import hashlib
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from makima.tools.registry import ToolRegistry


SAFE_ROOT_PREFIX = "makima-osworld-safe-"


@dataclass(frozen=True)
class SafeTask:
    """A deterministic task specification with fixed seed and output files."""

    task_id: str
    title: str
    instruction: str
    seed_files: Mapping[str, str]
    output_files: tuple[str, ...]


def _release_task() -> SafeTask:
    seed = {
        "workspace/README.txt": (
            "Makima Release Workspace\n"
            "Owner: Platform Team\n"
            "Release: 2026.10\n"
            "Use the metrics file and the 95% pass-rate policy.\n"
        ),
        "workspace/metrics.csv": (
            "component,tests,passed\n"
            "api,120,118\n"
            "ui,80,80\n"
            "worker,60,57\n"
        ),
        "workspace/policy.txt": (
            "Release threshold: pass_rate >= 0.95\n"
            "Report percentages with two decimal places.\n"
            "Overall is PASS only when every component passes.\n"
        ),
    }
    instruction = """Complete the release-readiness task in the seeded workspace.

1. Inspect every seeded file under `workspace/` and use the policy, not guesswork.
2. Calculate each component's passed/tests percentage from `metrics.csv`.
3. Create `workspace/release_report.md` with exactly this structure and no extra
   prose: a `# Release Readiness` heading, one bullet per component in the
   existing CSV order using `component: passed/tests (XX.XX%) - PASS|FAIL`, and
   a final `Overall: PASS|FAIL` line. A component passes at 95.00% or above.
4. Create `workspace/release_manifest.sha256` containing one sorted line for
   each source file and `release_report.md`, formatted
   `<sha256>  <relative-path>`. Do not include the manifest itself.
5. Run the evaluator and report its result. Do not create any other files.

This is a fenced Windows benchmark. Do not delete files, kill processes, use a
shell, browse, change settings, send messages, or access paths outside the
benchmark workspace. Only use the explicitly provided tools."""
    return SafeTask(
        task_id="windows-files-001",
        title="Release readiness reconciliation",
        instruction=instruction,
        seed_files=seed,
        output_files=("workspace/release_report.md", "workspace/release_manifest.sha256"),
    )


def _queue_task() -> SafeTask:
    seed = {
        "inbox/README.txt": (
            "Action queue rules\n"
            "Keep only non-Done work. Sort by priority High, Medium, Low; then due date.\n"
            "Preserve task_id, owner, due_date, and notes in the output.\n"
        ),
        "inbox/tasks.csv": (
            "task_id,owner,status,priority,due_date,notes\n"
            "T-104,Aria,Open,High,2026-10-08,Rotate credentials\n"
            "T-101,Bo,Done,High,2026-10-05,Already shipped\n"
            "T-109,Cleo,Open,Low,2026-10-04,Update screenshot\n"
            "T-103,Dev,In Progress,Medium,2026-10-03,Review error budget\n"
            "T-107,Eli,Open,High,2026-10-11,Verify rollback\n"
        ),
    }
    instruction = """Complete the inbox triage task in the seeded workspace.

1. Inspect `inbox/README.txt` and `inbox/tasks.csv`.
2. Create `inbox/action_queue.csv` with the exact header
   `task_id,owner,due_date,notes`, excluding every row whose status is `Done`.
   Sort remaining rows by priority High, then Medium, then Low, and within each
   priority by ascending due_date. Do not add a priority column to the output.
3. Create `inbox/summary.txt` with exactly three lines:
   `Open: N`, `In Progress: N`, and `Done: N`, counting the original CSV rows.
4. Run the evaluator. Do not create any other files.

This is a fenced Windows benchmark. Do not delete files, kill processes, use a
shell, browse, change settings, send messages, or access paths outside the
benchmark workspace. Only use the explicitly provided tools."""
    return SafeTask(
        task_id="windows-files-002",
        title="Inbox action-queue triage",
        instruction=instruction,
        seed_files=seed,
        output_files=("inbox/action_queue.csv", "inbox/summary.txt"),
    )


SAFE_TASKS: Dict[str, SafeTask] = {
    task.task_id: task for task in (_release_task(), _queue_task())
}


def list_safe_tasks() -> list[dict[str, str]]:
    """Return public metadata without exposing expected answers."""
    return [{"task_id": task.task_id, "title": task.title} for task in SAFE_TASKS.values()]


class SafeWindowsBenchmark:
    """Own one temporary directory and at most one Notepad child process."""

    def __init__(self, task_id: str = "windows-files-001", root: Optional[Path] = None) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("The safe Windows benchmark must run on Windows.")
        if task_id not in SAFE_TASKS:
            raise ValueError(f"Unknown safe task: {task_id}")
        self.task = SAFE_TASKS[task_id]
        self.root = (root or Path(tempfile.mkdtemp(prefix=SAFE_ROOT_PREFIX))).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._notepad: Optional[subprocess.Popen[Any]] = None
        self._closed = False
        self._events: list[dict[str, Any]] = []
        self._cleanup_error: Optional[str] = None

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def _event(self, tool: str, outcome: str, **details: Any) -> None:
        if len(self._events) >= 100:
            return
        self._events.append({"tool": tool, "outcome": outcome, **details})

    def _relative_path(self, filename: str) -> str:
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("filename must be a non-empty relative path")
        candidate = Path(filename)
        if candidate.is_absolute() or any(part in ("", ".", "..") for part in candidate.parts):
            raise ValueError("Only normalized relative paths are allowed")
        normalized = candidate.as_posix()
        allowed = set(self.task.seed_files) | set(self.task.output_files)
        if normalized not in allowed:
            raise ValueError(f"Path is not allowlisted for task {self.task.task_id}: {normalized}")
        return normalized

    def _owned_path(self, filename: str) -> Path:
        relative = self._relative_path(filename)
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Path escaped the owned benchmark directory") from exc
        return candidate

    def _all_files(self) -> list[str]:
        return sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file())

    def prepare_task(self) -> Dict[str, Any]:
        """Reset only the harness-owned seed files before the agent loop."""
        for filename, content in self.task.seed_files.items():
            path = self._owned_path(filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        self._event("setup_task", "ok", task_id=self.task.task_id, seed_files=sorted(self.task.seed_files))
        return {"task_id": self.task.task_id, "title": self.task.title, "seeded_files": sorted(self.task.seed_files)}

    def get_windows_environment(self) -> Dict[str, Any]:
        """Return read-only host facts needed by the test."""
        result = {
            "platform": platform.platform(),
            "system": platform.system(),
            "python": platform.python_version(),
            "benchmark_root": str(self.root),
            "task_id": self.task.task_id,
            "allowed_operations": [
                "get_windows_environment", "list_safe_tasks", "list_task_files",
                "read_task_file", "write_task_file", "compute_task_manifest",
                "evaluate_task", "open_task_file_in_notepad",
            ],
        }
        self._event("get_windows_environment", "ok")
        return result

    def list_task_files(self) -> Dict[str, Any]:
        """List only files and digests inside the harness-owned task workspace."""
        files = []
        for filename in self._all_files():
            path = self._owned_path(filename)
            files.append({"path": filename, "bytes": path.stat().st_size, "sha256": self._sha256(path)})
        self._event("list_task_files", "ok", file_count=len(files))
        return {"task_id": self.task.task_id, "files": files}

    def read_task_file(self, filename: str) -> Dict[str, Any]:
        """Read one allowlisted task file and return its digest."""
        path = self._owned_path(filename)
        if not path.is_file():
            raise FileNotFoundError(f"Task file has not been created: {filename}")
        content = path.read_text(encoding="utf-8")
        self._event("read_task_file", "ok", path=filename, bytes=len(content.encode("utf-8")))
        return {"path": filename, "text": content, "sha256": self._sha256(path)}

    def write_task_file(self, filename: str, content: str) -> Dict[str, Any]:
        """Write only an expected output file inside the owned workspace."""
        if filename not in self.task.output_files:
            raise ValueError("Writes are limited to the task's expected output files")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 32_768:
            raise ValueError("Output must be text no larger than 32 KiB")
        if "\x00" in content:
            raise ValueError("NUL bytes are not allowed")
        path = self._owned_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        self._event("write_task_file", "ok", path=filename, bytes=path.stat().st_size)
        return {"path": filename, "sha256": self._sha256(path), "bytes": path.stat().st_size}

    def compute_task_manifest(self) -> Dict[str, Any]:
        """Compute sorted SHA-256 lines for all non-manifest files."""
        lines = []
        for filename in sorted(self._all_files()):
            if filename.endswith(".sha256"):
                continue
            path = self._owned_path(filename)
            lines.append(f"{self._sha256(path)}  {filename}")
        self._event("compute_task_manifest", "ok", file_count=len(lines))
        return {"task_id": self.task.task_id, "manifest": "\n".join(lines) + ("\n" if lines else ""), "files": len(lines)}

    def evaluate_task(self) -> Dict[str, Any]:
        """Run the executable post-task evaluator against the actual workspace."""
        actual_files = set(self._all_files())
        allowed_files = set(self.task.seed_files) | set(self.task.output_files)
        missing = sorted(set(self.task.output_files) - actual_files)
        unexpected = sorted(actual_files - allowed_files)
        checks: dict[str, Any] = {
            "required_outputs_present": not missing,
            "no_unexpected_files": not unexpected,
        }
        if self.task.task_id == "windows-files-001":
            checks.update(_evaluate_release_outputs(self))
        else:
            expected = _expected_outputs(self.task)
            for filename, expected_content in expected.items():
                path = self._owned_path(filename)
                checks[f"exact:{filename}"] = (
                    path.is_file()
                    and _normalise_text(path.read_text(encoding="utf-8")) == _normalise_text(expected_content)
                )
        passed = all(checks.values()) and not missing and not unexpected
        result = {
            "task_id": self.task.task_id,
            "passed": passed,
            "checks": checks,
            "missing_outputs": missing,
            "unexpected_files": unexpected,
            "observed_files": sorted(actual_files),
        }
        self._event("evaluate_task", "passed" if passed else "failed", checks=checks)
        return result

    def open_task_file_in_notepad(self, filename: str) -> Dict[str, Any]:
        """Open only an expected task output in a harness-owned Notepad child."""
        if filename not in self.task.output_files:
            raise ValueError("Notepad access is limited to expected task outputs")
        path = self._owned_path(filename)
        if not path.is_file():
            raise FileNotFoundError(f"Create the output before opening it: {filename}")
        if self._notepad is None or self._notepad.poll() is not None:
            self._notepad = subprocess.Popen(["notepad.exe", str(path)], shell=False)
        self._event("open_task_file_in_notepad", "ok", path=filename, pid=self._notepad.pid)
        return {"opened": True, "pid": self._notepad.pid, "path": filename}

    def close(self) -> None:
        """Close only the owned Notepad child and remove only the owned temp tree."""
        if self._closed:
            return
        self._closed = True
        if self._notepad is not None and self._notepad.poll() is None:
            self._notepad.terminate()
            try:
                self._notepad.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._cleanup_error = "owned Notepad did not exit within 3 seconds"
        if self.root.name.startswith(SAFE_ROOT_PREFIX) and self.root.parent == Path(tempfile.gettempdir()).resolve():
            try:
                shutil.rmtree(self.root, ignore_errors=False)
            except OSError as exc:
                self._cleanup_error = f"owned temp cleanup failed: {type(exc).__name__}: {exc}"

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


def _release_expected(task: SafeTask) -> Dict[str, str]:
    metrics = list(csv.DictReader(task.seed_files["workspace/metrics.csv"].splitlines()))
    rows = []
    all_pass = True
    for row in metrics:
        rate = int(row["passed"]) / int(row["tests"])
        passed = rate >= 0.95
        all_pass = all_pass and passed
        rows.append(f"- {row['component']}: {row['passed']}/{row['tests']} ({rate:.2%}) - {'PASS' if passed else 'FAIL'}")
    report = "# Release Readiness\n" + "\n".join(rows) + f"\nOverall: {'PASS' if all_pass else 'FAIL'}\n"
    files = dict(task.seed_files)
    files["workspace/release_report.md"] = report
    manifest = "".join(f"{hashlib.sha256(files[name].encode('utf-8')).hexdigest()}  {name}\n" for name in sorted(files))
    return {"workspace/release_report.md": report, "workspace/release_manifest.sha256": manifest}


def _normalise_text(value: str) -> str:
    """Ignore platform newline and final-newline differences, not content."""
    return value.replace("\r\n", "\n").rstrip("\n")


def _evaluate_release_outputs(harness: SafeWindowsBenchmark) -> Dict[str, bool]:
    """Semantically evaluate the report, then bind the manifest to its bytes."""
    report_path = harness._owned_path("workspace/release_report.md")
    manifest_path = harness._owned_path("workspace/release_manifest.sha256")
    checks: Dict[str, bool] = {
        "release_report_semantics": False,
        "release_manifest_matches_observed_report": False,
    }
    if not report_path.is_file() or not manifest_path.is_file():
        return checks

    rows = list(csv.DictReader(harness.task.seed_files["workspace/metrics.csv"].splitlines()))
    report_lines = _normalise_text(report_path.read_text(encoding="utf-8")).split("\n")
    expected_lines = ["# Release Readiness"]
    all_pass = True
    for row in rows:
        rate = int(row["passed"]) / int(row["tests"])
        status = "PASS" if rate >= 0.95 else "FAIL"
        all_pass = all_pass and status == "PASS"
        expected_lines.append(
            f"- {row['component']}: {row['passed']}/{row['tests']} ({rate:.2%}) - {status}"
        )
    expected_lines.append(f"Overall: {'PASS' if all_pass else 'FAIL'}")
    if len(report_lines) == len(expected_lines):
        report_ok = report_lines[0] == expected_lines[0] and report_lines[-1] == expected_lines[-1]
        for observed, source_row in zip(report_lines[1:-1], rows):
            match = re.fullmatch(r"-\s*([^:]+):\s*(\d+)\s*/\s*(\d+)\s*\((\d+\.\d{2})%\)\s*(?:-|—)\s*(PASS|FAIL)", observed)
            if not match:
                report_ok = False
                break
            component, passed, tests, percentage, status = match.groups()
            expected_rate = int(source_row["passed"]) / int(source_row["tests"])
            expected_status = "PASS" if expected_rate >= 0.95 else "FAIL"
            report_ok = report_ok and (
                component == source_row["component"]
                and passed == source_row["passed"]
                and tests == source_row["tests"]
                and percentage == f"{expected_rate:.2%}".rstrip("%")
                and status == expected_status
            )
        checks["release_report_semantics"] = report_ok

    files = dict(harness.task.seed_files)
    files["workspace/release_report.md"] = report_path.read_text(encoding="utf-8")
    expected_manifest = "".join(
        f"{hashlib.sha256(files[name].encode('utf-8')).hexdigest()}  {name}\n" for name in sorted(files)
    )
    checks["release_manifest_matches_observed_report"] = (
        _normalise_text(manifest_path.read_text(encoding="utf-8")) == _normalise_text(expected_manifest)
    )
    return checks


def _queue_expected(task: SafeTask) -> Dict[str, str]:
    rows = list(csv.DictReader(task.seed_files["inbox/tasks.csv"].splitlines()))
    rank = {"High": 0, "Medium": 1, "Low": 2}
    active = [row for row in rows if row["status"] != "Done"]
    active.sort(key=lambda row: (rank[row["priority"]], row["due_date"]))
    lines = ["task_id,owner,due_date,notes"]
    lines.extend(f"{r['task_id']},{r['owner']},{r['due_date']},{r['notes']}" for r in active)
    counts = {status: sum(row["status"] == status for row in rows) for status in ("Open", "In Progress", "Done")}
    return {
        "inbox/action_queue.csv": "\n".join(lines) + "\n",
        "inbox/summary.txt": "\n".join(f"{status}: {counts[status]}" for status in ("Open", "In Progress", "Done")) + "\n",
    }


def _expected_outputs(task: SafeTask) -> Dict[str, str]:
    if task.task_id == "windows-files-001":
        return _release_expected(task)
    if task.task_id == "windows-files-002":
        return _queue_expected(task)
    raise ValueError(f"No evaluator registered for task {task.task_id}")


def _tracked(harness: SafeWindowsBenchmark, method: Callable[..., Any]) -> Callable[..., Any]:
    """Add a bounded event record while preserving the original tool signature."""
    @wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            harness._event(getattr(method, "__name__", "tool"), "error", error=f"{type(exc).__name__}: {exc}")
            raise
    return wrapper


def build_safe_registry(harness: SafeWindowsBenchmark) -> ToolRegistry:
    """Build an explicit allowlist; Makima auto-discovery is intentionally disabled."""
    registry = ToolRegistry(name="windows-safe-osworld")
    registry.register(_tracked(harness, harness.get_windows_environment), description="Read-only Windows environment facts.")
    registry.register(_tracked(harness, list_safe_tasks), description="List the available safe benchmark task IDs.")
    registry.register(_tracked(harness, harness.list_task_files), description="List files and SHA-256 digests inside the owned task workspace.")
    registry.register(_tracked(harness, harness.read_task_file), description="Read one allowlisted task file from the owned workspace.")
    registry.register(_tracked(harness, harness.write_task_file), description="Write only an expected output file in the owned workspace.")
    registry.register(_tracked(harness, harness.compute_task_manifest), description="Compute sorted SHA-256 manifest lines for task files.")
    registry.register(_tracked(harness, harness.evaluate_task), description="Run the executable exact-output evaluator.")
    registry.register(_tracked(harness, harness.open_task_file_in_notepad), description="Open only an expected task output in Notepad.")
    return registry


# Backwards-compatible smoke instruction for callers that imported it earlier.
SAFE_TASK_INSTRUCTION = _release_task().instruction
