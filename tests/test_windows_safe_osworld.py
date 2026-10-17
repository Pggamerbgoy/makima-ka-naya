"""Contract tests for the bounded Windows OSWorld-inspired benchmark."""

from __future__ import annotations

import platform

import pytest

from benchmarks.windows_safe_osworld import (
    SAFE_TASKS,
    SafeWindowsBenchmark,
    _expected_outputs,
    build_safe_registry,
    list_safe_tasks,
)


pytestmark = pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only harness")


def test_safe_registry_is_explicit_and_allowlisted() -> None:
    harness = SafeWindowsBenchmark()
    try:
        names = set(build_safe_registry(harness).list_names())
        assert names == {
            "get_windows_environment",
            "list_safe_tasks",
            "list_task_files",
            "read_task_file",
            "write_task_file",
            "compute_task_manifest",
            "evaluate_task",
            "open_task_file_in_notepad",
        }
    finally:
        harness.close()


def test_task_catalog_does_not_expose_expected_answers() -> None:
    catalog = list_safe_tasks()
    assert {item["task_id"] for item in catalog} == set(SAFE_TASKS)
    assert all("expected" not in item for item in catalog)


@pytest.mark.parametrize("task_id", tuple(SAFE_TASKS))
def test_each_task_evaluator_accepts_only_exact_outputs(task_id: str) -> None:
    harness = SafeWindowsBenchmark(task_id=task_id)
    try:
        harness.prepare_task()
        assert harness.evaluate_task()["passed"] is False
        expected = _expected_outputs(harness.task)
        for filename, content in expected.items():
            harness.write_task_file(filename, content)
        evaluation = harness.evaluate_task()
        assert evaluation["passed"] is True
        assert evaluation["unexpected_files"] == []
    finally:
        harness.close()


def test_path_and_write_guards_reject_escape_and_unapproved_files() -> None:
    harness = SafeWindowsBenchmark()
    try:
        harness.prepare_task()
        with pytest.raises(ValueError):
            harness.read_task_file("..\\outside.txt")
        with pytest.raises(ValueError):
            harness.read_task_file("C:\\Windows\\win.ini")
        with pytest.raises(ValueError):
            harness.write_task_file("workspace/extra.txt", "no")
    finally:
        harness.close()


def test_manifest_is_sorted_and_excludes_manifest_itself() -> None:
    harness = SafeWindowsBenchmark()
    try:
        harness.prepare_task()
        manifest = harness.compute_task_manifest()["manifest"]
        lines = manifest.splitlines()
        paths = [line.split("  ", 1)[1] for line in lines]
        assert paths == sorted(paths)
        assert all(".sha256" not in line for line in lines)
        assert len(lines) == len(harness.task.seed_files)
    finally:
        harness.close()
