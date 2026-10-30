"""
Makima v2 — Hardware & Local Git Version Control Tools.
Provides safe, non-interactive Git operations for local coding workspaces.
Enforces non-blocking execution (GIT_TERMINAL_PROMPT=0, PAGER=cat) to prevent terminal hangs.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from makima.tools.registry import tool

logger = logging.getLogger(__name__)


def _resolve_repo_path(repo_path: Optional[str] = None) -> Path:
    """Resolves repo directory, defaulting to current working directory."""
    if repo_path and repo_path.strip():
        p = Path(repo_path).resolve()
        if p.is_dir():
            return p
    return Path.cwd().resolve()


def _run_git(
    args: List[str],
    repo_path: Optional[str] = None,
    timeout: int = 20,
) -> Tuple[bool, str, str, int]:
    """
    Executes a Git command non-interactively with strict environment safeguards.

    Returns:
        Tuple of (success: bool, stdout: str, stderr: str, returncode: int).
    """
    if not shutil.which("git"):
        return False, "", "Git executable not found in system PATH.", 127

    target_dir = _resolve_repo_path(repo_path)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["PAGER"] = "cat"
    env["GIT_PAGER"] = "cat"
    env["LC_ALL"] = "C"

    cmd = ["git"] + args
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(target_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        success = proc.returncode == 0
        return success, proc.stdout.strip(), proc.stderr.strip(), proc.returncode
    except subprocess.TimeoutExpired:
        return False, "", f"Git command '{' '.join(cmd)}' timed out after {timeout}s.", -1
    except Exception as exc:
        return False, "", f"Git execution error: {exc}", -2


@tool(
    name="git_status",
    description="Inspect the Git status of a local repository. Returns current branch, clean/dirty state, and lists of staged, modified, and untracked files.",
    tags=["development", "git", "vcs"],
    purpose="Inspect repository status before making changes or commits.",
    side_effect="Read-only; does not alter repository state.",
)
def git_status(repo_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Inspect local repository status.

    Args:
        repo_path: Path to the local git repository (defaults to current directory).

    Returns:
        Structured dictionary with branch name, status, and categorized file lists.
    """
    target_dir = _resolve_repo_path(repo_path)

    # Verify git repository
    ok, stdout, stderr, code = _run_git(["rev-parse", "--is-inside-work-tree"], repo_path=str(target_dir))
    if not ok:
        return {
            "success": False,
            "error": f"'{target_dir}' is not a valid Git repository: {stderr or 'rev-parse failed'}",
            "repo_path": str(target_dir),
        }

    # Branch name
    _, branch, _, _ = _run_git(["branch", "--show-current"], repo_path=str(target_dir))
    if not branch:
        _, branch, _, _ = _run_git(["rev-parse", "--short", "HEAD"], repo_path=str(target_dir))
        branch = f"detached ({branch})" if branch else "main"

    # Porcelain status
    _, status_out, _, _ = _run_git(["status", "--porcelain=v1"], repo_path=str(target_dir))

    staged: List[str] = []
    modified: List[str] = []
    untracked: List[str] = []
    deleted: List[str] = []

    if status_out:
        for line in status_out.splitlines():
            if len(line) < 3:
                continue
            index_code = line[0]
            work_code = line[1]
            fname = line[3:].strip()

            if index_code in ("M", "A", "R", "C"):
                staged.append(fname)
            elif index_code == "D":
                staged.append(f"deleted: {fname}")

            if work_code == "M":
                modified.append(fname)
            elif work_code == "D":
                deleted.append(fname)
            elif index_code == "?" and work_code == "?":
                untracked.append(fname)

    is_clean = len(staged) == 0 and len(modified) == 0 and len(untracked) == 0 and len(deleted) == 0

    return {
        "success": True,
        "repo_path": str(target_dir),
        "branch": branch,
        "is_clean": is_clean,
        "staged_count": len(staged),
        "staged": staged,
        "modified_count": len(modified),
        "modified": modified,
        "untracked_count": len(untracked),
        "untracked": untracked,
        "deleted": deleted,
    }


@tool(
    name="git_diff",
    description="Show changes between commits, commit and working tree, or staged changes.",
    tags=["development", "git", "vcs"],
    purpose="Inspect exact code diffs before committing or debugging.",
    side_effect="Read-only; does not alter files.",
)
def git_diff(
    repo_path: Optional[str] = None,
    staged: bool = False,
    file_path: Optional[str] = None,
    max_lines: int = 150,
) -> Dict[str, Any]:
    """
    Retrieve unpaged git diff.

    Args:
        repo_path: Local repo directory path.
        staged: If True, inspects staged changes (git diff --cached).
        file_path: Optional specific file to filter diff.
        max_lines: Maximum diff lines to return (prevents context blowout).

    Returns:
        Structured dictionary with diff text, line count, and truncation notice.
    """
    args = ["diff"]
    if staged:
        args.append("--cached")
    if file_path:
        args.extend(["--", file_path])

    ok, stdout, stderr, code = _run_git(args, repo_path=repo_path)
    if not ok:
        return {"success": False, "error": stderr or "Diff failed", "code": code}

    lines = stdout.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True

    return {
        "success": True,
        "staged": staged,
        "file_filter": file_path,
        "lines_count": len(lines),
        "truncated": truncated,
        "diff": "\n".join(lines),
    }


@tool(
    name="git_commit",
    description="Stage modified files and create a Git commit with a descriptive commit message.",
    tags=["development", "git", "vcs"],
    purpose="Safely commit project changes non-interactively.",
    side_effect="Creates a new commit in the local Git repository.",
)
def git_commit(
    message: str,
    repo_path: Optional[str] = None,
    add_all: bool = True,
) -> Dict[str, Any]:
    """
    Create a Git commit non-interactively.

    Args:
        message: Descriptive commit message.
        repo_path: Optional repository path.
        add_all: If True (default), runs 'git add -A' before committing.

    Returns:
        Dictionary reporting success, commit hash, and summary.
    """
    clean_msg = (message or "").strip()
    if not clean_msg:
        return {"success": False, "error": "Commit message cannot be empty."}

    target_dir = _resolve_repo_path(repo_path)

    if add_all:
        ok, _, stderr, _ = _run_git(["add", "-A"], repo_path=str(target_dir))
        if not ok:
            return {"success": False, "error": f"Failed staging files: {stderr}"}

    ok, stdout, stderr, code = _run_git(["commit", "-m", clean_msg], repo_path=str(target_dir))
    if not ok:
        if "nothing to commit" in (stdout + stderr).lower():
            return {
                "success": True,
                "action": "no_changes",
                "message": "Nothing to commit, working tree is clean.",
            }
        return {"success": False, "error": stderr or stdout or "Commit failed", "code": code}

    # Retrieve created commit hash
    _, commit_hash, _, _ = _run_git(["rev-parse", "--short", "HEAD"], repo_path=str(target_dir))

    return {
        "success": True,
        "commit_hash": commit_hash,
        "message": clean_msg,
        "output": stdout,
    }


@tool(
    name="git_log",
    description="Read the recent commit history of a local Git repository.",
    tags=["development", "git", "vcs"],
    purpose="Inspect recent commits, authors, and dates.",
    side_effect="Read-only; does not alter repository history.",
)
def git_log(
    repo_path: Optional[str] = None,
    limit: int = 5,
) -> Dict[str, Any]:
    """
    Retrieve structured recent commit logs.

    Args:
        repo_path: Local repo directory path.
        limit: Number of recent commits to return (default: 5).

    Returns:
        Structured list of commit records.
    """
    n = max(1, min(limit, 50))
    args = ["log", f"-n{n}", "--pretty=format:%h|%an|%ad|%s", "--date=short"]
    ok, stdout, stderr, code = _run_git(args, repo_path=repo_path)
    if not ok:
        return {"success": False, "error": stderr or "Log query failed", "commits": []}

    commits: List[Dict[str, str]] = []
    if stdout:
        for line in stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "summary": parts[3],
                })

    return {
        "success": True,
        "count": len(commits),
        "commits": commits,
    }
