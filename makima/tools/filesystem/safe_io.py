"""
Makima v2 — Safe Filesystem I/O Engine.
Architectural Pattern: Hermes-style safe filesystem tools with strict boundary clamping and SAGA integration.
Zero-Hardcoding Guarantee: Fully dynamic workspace path resolution via MakimaConfig with thread-safe overrides.
Boundary Security: Enforces path.resolve().is_relative_to(workspace_dir.resolve()) to prevent directory traversal.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Pattern

from makima.tools.registry import ToolError, tool

if TYPE_CHECKING:
    from makima.tools.filesystem.saga_rollback import SagaRollbackManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Security Exceptions
# ---------------------------------------------------------------------------

class BoundaryTraversalError(PermissionError, ToolError):
    """Raised when a path resolves outside the permitted workspace directory."""
    pass


class ProtectedCredentialError(PermissionError, ToolError):
    """Raised when an operation attempts to access protected credentials or sensitive files."""
    pass


# Strict deny-list for sensitive credentials, secret keys, and browser databases
PROTECTED_CREDENTIAL_PATTERNS: List[Pattern[str]] = [
    re.compile(r"^\.env([._-].+)?$", re.IGNORECASE),
    re.compile(r"^id_(rsa|ed25519|ecdsa|dsa)(\.pub)?$", re.IGNORECASE),
    re.compile(r".*\.(pem|key|pfx|p12)$", re.IGNORECASE),
    re.compile(r".*(credential|secret|service[-_]account).*\.json$", re.IGNORECASE),
    re.compile(r"^(login data|cookies\.sqlite|web data)$", re.IGNORECASE),
    re.compile(r"^(sam|system|security|ntuser\.dat|wallet\.dat)$", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Dynamic Workspace Resolution
# ---------------------------------------------------------------------------

_workspace_lock = threading.RLock()
_custom_workspace_dir: Optional[Path] = None


def get_workspace_dir() -> Path:
    """
    Dynamically returns the resolved workspace directory.
    Uses custom override if set, otherwise reads from MakimaConfig settings.
    Ensures directory exists before returning.
    """
    global _custom_workspace_dir
    with _workspace_lock:
        if _custom_workspace_dir is not None:
            _custom_workspace_dir.mkdir(parents=True, exist_ok=True)
            return _custom_workspace_dir

    try:
        from makima.config import get_settings
        settings = get_settings()
        ws = settings.workspace_dir_path.resolve()
        ws.mkdir(parents=True, exist_ok=True)
        return ws
    except Exception as exc:
        logger.debug("Falling back to cwd/workspace due to config lookup failure: %s", exc)
        fallback = (Path.cwd() / "workspace").resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def set_workspace_dir(path: Optional[Path | str]) -> None:
    """
    Sets or resets the dynamic workspace directory override.
    Useful for test sandboxes, multi-tenant agent instances, or isolated runs.

    Args:
        path: Path to target directory, or None to revert to default config.
    """
    global _custom_workspace_dir
    with _workspace_lock:
        if path is None:
            _custom_workspace_dir = None
        else:
            resolved = Path(path).resolve()
            resolved.mkdir(parents=True, exist_ok=True)
            _custom_workspace_dir = resolved


def resolve_safe_path(path: Path | str, workspace_dir: Optional[Path | str] = None) -> Path:
    """
    Strict boundary clamping helper.
    Resolves relative and absolute paths against workspace_dir and verifies
    that resolved_path.is_relative_to(workspace_dir.resolve()).

    Args:
        path: Target file or directory path string or Path object.
        workspace_dir: Optional custom workspace boundary (defaults to get_workspace_dir()).

    Returns:
        Path: Canonical resolved path strictly inside the workspace boundary.

    Raises:
        BoundaryTraversalError: If path resolves outside the workspace boundary.
    """
    ws = Path(workspace_dir).resolve() if workspace_dir is not None else get_workspace_dir().resolve()
    target = Path(path)

    if target.is_absolute():
        resolved = target.resolve()
    else:
        resolved = (ws / target).resolve()

    try:
        is_safe = resolved.is_relative_to(ws)
    except (ValueError, TypeError):
        is_safe = False

    if not is_safe:
        raise BoundaryTraversalError(
            f"Security Boundary Violation: Path '{path}' resolves to '{resolved}', "
            f"which escapes the permitted workspace boundary '{ws}'."
        )

    # Protected credential & sensitive file pattern deny-list
    for part in resolved.parts:
        for pat in PROTECTED_CREDENTIAL_PATTERNS:
            if pat.search(part):
                raise ProtectedCredentialError(
                    f"Protected Credential Access Denied: Path '{resolved.name}' matches protected sensitive file pattern. "
                    "Access is strictly blocked by Makima security guardrails."
                )

    return resolved


def _get_saga_manager() -> SagaRollbackManager:
    """Lazy importer for SagaRollbackManager to eliminate circular import issues."""
    from makima.tools.filesystem.saga_rollback import SagaRollbackManager
    return SagaRollbackManager.get_instance()


# ---------------------------------------------------------------------------
# Registered Safe Filesystem Tools
# ---------------------------------------------------------------------------

@tool(
    name="read_file",
    description=(
        "Use when you need to read the content of a file in the workspace. "
        "Do not use for files outside the workspace — use execute_command with 'type' or 'cat' for those."
    ),
    tags=["filesystem", "read", "io"],
)
def read_file(path: str, encoding: str = "utf-8") -> str:
    """
    Read the contents of a text file located within the workspace boundary.

    Args:
        path: Path to the target file relative to the workspace boundary.
        encoding: Character encoding used to read the file (defaults to 'utf-8').

    Returns:
        The content of the file as a string.

    Raises:
        BoundaryTraversalError: If path resolves outside the workspace boundary.
        FileNotFoundError: If the target file does not exist.
        IsADirectoryError: If the target path points to a directory.
    """
    resolved = resolve_safe_path(path)

    if not resolved.exists():
        raise FileNotFoundError(f"File not found: '{path}' (resolved: '{resolved}')")

    if resolved.is_dir():
        raise IsADirectoryError(f"Target path is a directory, not a file: '{path}'")

    with open(resolved, "r", encoding=encoding, errors="replace", newline="") as f:
        return f.read()



@tool(
    name="write_file",
    description="Write text content to a file within the workspace boundary. Overwriting existing files requires overwrite=True and creates an automatic SAGA snapshot.",
    tags=["filesystem", "write", "io"],
)
def write_file(
    path: str,
    content: str,
    overwrite: bool = False,
    encoding: str = "utf-8",
) -> str:
    """
    Write text content to a file within the workspace boundary.

    Args:
        path: Destination path relative to the workspace boundary.
        content: Text content to write into the target file.
        overwrite: When True, permits replacing an existing file and takes a SAGA snapshot.
        encoding: Character encoding for writing (defaults to 'utf-8').

    Returns:
        Confirmation message detailing characters written and snapshot status.

    Raises:
        BoundaryTraversalError: If path resolves outside the workspace boundary.
        FileExistsError: If file exists and overwrite is False.
        IsADirectoryError: If destination is an existing directory.
    """
    resolved = resolve_safe_path(path)

    if resolved.is_dir():
        raise IsADirectoryError(f"Cannot write file: destination '{path}' is an existing directory.")

    file_existed = resolved.exists()

    if file_existed and not overwrite:
        raise FileExistsError(
            f"File '{path}' already exists. Specify overwrite=True to allow replacement."
        )

    # Take SAGA snapshot before destructive overwrite or initial creation
    manager = _get_saga_manager()
    operation = "overwrite" if file_existed else "create"
    snap = manager.create_snapshot(resolved, operation=operation)

    # Ensure parent directories exist
    resolved.parent.mkdir(parents=True, exist_ok=True)

    # Write atomically using a temporary file in the same directory
    with tempfile.NamedTemporaryFile("w", dir=resolved.parent, encoding=encoding, newline="", delete=False) as tf:
        tf.write(content)
        temp_name = tf.name

    os.replace(temp_name, str(resolved))

    action_label = "Overwrote" if file_existed else "Created"
    return (
        f"Successfully {action_label.lower()} '{path}' ({len(content)} chars written). "
        f"Snapshot ID: {snap.snapshot_id}"
    )


@tool(
    name="edit_file",
    description="Edit an existing file in the workspace by replacing target_text with replacement_text. Automatically creates a SAGA snapshot before modification.",
    tags=["filesystem", "edit", "io"],
)
def edit_file(
    path: str,
    target_text: str,
    replacement_text: str,
    replace_all: bool = False,
    encoding: str = "utf-8",
) -> str:
    """
    Edit an existing file in the workspace by replacing target_text with replacement_text.

    Args:
        path: Path to the target file within the workspace boundary.
        target_text: Exact string to find and replace.
        replacement_text: String to insert in place of target_text.
        replace_all: When True, replaces all occurrences; when False, replaces only the first occurrence.
        encoding: Character encoding used for read/write (defaults to 'utf-8').

    Returns:
        Confirmation message detailing replacement count and snapshot ID.

    Raises:
        BoundaryTraversalError: If path resolves outside the workspace boundary.
        FileNotFoundError: If the target file does not exist.
        IsADirectoryError: If the target path points to a directory.
        ValueError: If target_text is not found in the file content.
    """
    resolved = resolve_safe_path(path)

    if not resolved.exists():
        raise FileNotFoundError(f"File not found: '{path}' (resolved: '{resolved}')")

    if resolved.is_dir():
        raise IsADirectoryError(f"Cannot edit directory: '{path}'")

    with open(resolved, "r", encoding=encoding, errors="replace", newline="") as f:
        content = f.read()

    if target_text not in content:
        raise ValueError(
            f"Target text not found in '{path}'. Edit rejected to prevent corrupted state."
        )

    count = content.count(target_text)
    effective_count = count if replace_all else 1

    # Take SAGA snapshot before editing
    manager = _get_saga_manager()
    snap = manager.create_snapshot(resolved, operation="edit")

    # Perform replacement
    if replace_all:
        new_content = content.replace(target_text, replacement_text)
    else:
        new_content = content.replace(target_text, replacement_text, 1)

    # Write atomically
    with tempfile.NamedTemporaryFile("w", dir=resolved.parent, encoding=encoding, newline="", delete=False) as tf:
        tf.write(new_content)
        temp_name = tf.name

    os.replace(temp_name, str(resolved))

    return (
        f"Successfully edited '{path}' (replaced {effective_count} of {count} match(es)). "
        f"Snapshot ID: {snap.snapshot_id}"
    )


@tool(
    name="delete_file",
    description="Delete a file within the workspace boundary. Automatically creates a SAGA snapshot before removal.",
    tags=["filesystem", "delete", "io"],
)
def delete_file(path: str) -> str:
    """
    Delete a file within the workspace boundary. Automatically creates a SAGA snapshot.

    Args:
        path: Path to the file to delete relative to the workspace boundary.

    Returns:
        Confirmation message with snapshot ID.

    Raises:
        BoundaryTraversalError: If path resolves outside the workspace boundary or targets workspace root.
        FileNotFoundError: If the target file does not exist.
        IsADirectoryError: If the path is a non-empty directory.
    """
    resolved = resolve_safe_path(path)
    ws = get_workspace_dir().resolve()

    if resolved == ws:
        raise BoundaryTraversalError(f"Cannot delete workspace root directory: '{path}'")

    if not resolved.exists():
        raise FileNotFoundError(f"File not found: '{path}' (resolved: '{resolved}')")

    if resolved.is_dir():
        try:
            resolved.rmdir()
            return f"Successfully removed empty directory '{path}'."
        except OSError as exc:
            raise IsADirectoryError(
                f"Directory '{path}' is not empty. Remove files inside first."
            ) from exc

    # File exists: Take SAGA snapshot before deletion
    manager = _get_saga_manager()
    snap = manager.create_snapshot(resolved, operation="delete")

    resolved.unlink()

    return f"Successfully deleted '{path}'. Snapshot ID: {snap.snapshot_id}"


@tool(
    name="list_directory",
    description=(
        "Use when you need to see what files or folders exist in a workspace directory. "
        "Use recursive=True to see the full tree. "
        "For directories outside the workspace, use execute_command with 'dir' or 'ls'."
    ),
    tags=["filesystem", "list", "io"],
)
def list_directory(
    path: str = ".",
    recursive: bool = False,
    include_hidden: bool = False,
) -> List[Dict[str, Any]]:
    """
    List files and subdirectories within a specified workspace path.

    Args:
        path: Directory path relative to workspace boundary (defaults to workspace root '.').
        recursive: If True, lists all descendants recursively. Defaults to False.
        include_hidden: If True, includes hidden dotfiles (excluding internal .snapshots). Defaults to False.

    Returns:
        List of item dictionaries containing name, path, type, size_bytes, and modified_at.

    Raises:
        BoundaryTraversalError: If path resolves outside the workspace boundary.
        FileNotFoundError: If the target directory does not exist.
        NotADirectoryError: If the target path is a file, not a directory.
    """
    resolved = resolve_safe_path(path)
    ws = get_workspace_dir().resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"Directory not found: '{path}' (resolved: '{resolved}')")

    if not resolved.is_dir():
        raise NotADirectoryError(f"Target path is not a directory: '{path}'")

    results: List[Dict[str, Any]] = []

    def _process_item(item: Path) -> None:
        if item.name == ".snapshots":
            return  # Always filter internal SAGA snapshot directory

        if not include_hidden and item.name.startswith("."):
            return

        try:
            st = item.stat()
            is_dir = item.is_dir()
            rel_path = str(item.relative_to(ws)).replace("\\", "/")
            mod_time = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()

            results.append({
                "name": item.name,
                "path": rel_path,
                "type": "directory" if is_dir else "file",
                "size_bytes": st.st_size if not is_dir else 0,
                "modified_at": mod_time,
            })
        except (OSError, PermissionError) as exc:
            logger.debug("Skipping unreadable item '%s': %s", item, exc)

    if recursive:
        for root, dirs, files in os.walk(resolved):
            root_path = Path(root)
            if root_path.name == ".snapshots" or ".snapshots" in root_path.parts:
                continue
            if not include_hidden and root_path.name.startswith(".") and root_path != resolved:
                continue

            for d in dirs:
                _process_item(root_path / d)
            for f in files:
                _process_item(root_path / f)
    else:
        for item in resolved.iterdir():
            _process_item(item)

    # Sort directories first, then alphabetical
    results.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
    return results


@tool(
    name="search_files",
    description="Search text content across files in the workspace using regex or keywords with line numbers and file pattern filtering.",
    tags=["filesystem", "search", "code", "grep"],
)
def search_files(
    query: str,
    path: str = ".",
    file_pattern: str = "*",
    max_results: int = 50,
    case_sensitive: bool = False,
) -> List[Dict[str, Any]]:
    """
    Search for text or regex patterns across files in the workspace.

    Args:
        query: Search term or regular expression pattern.
        path: Root directory to search within (defaults to workspace root).
        file_pattern: Glob pattern to filter filenames (e.g. '*.py', '*.ts', '*.json').
        max_results: Maximum number of matching lines to return (defaults to 50).
        case_sensitive: Whether search should be case sensitive (defaults to False).

    Returns:
        List of match dictionaries containing file_path, line_number, line_content, and match_count.
    """
    resolved = resolve_safe_path(path)
    ws = get_workspace_dir().resolve()

    if not resolved.exists() or not resolved.is_dir():
        return []

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(query, flags)
    except re.error:
        regex = re.compile(re.escape(query), flags)

    matches: List[Dict[str, Any]] = []

    for root, dirs, files in os.walk(resolved):
        root_path = Path(root)
        if ".snapshots" in root_path.parts or ".git" in root_path.parts or "node_modules" in root_path.parts:
            continue

        for f in files:
            if not Path(f).match(file_pattern):
                continue

            file_path = root_path / f
            try:
                rel_path = str(file_path.relative_to(ws)).replace("\\", "/")
                with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
                    for line_idx, line in enumerate(fh, 1):
                        if regex.search(line):
                            matches.append({
                                "file": rel_path,
                                "line": line_idx,
                                "content": line.strip()[:200],
                            })
                            if len(matches) >= max_results:
                                return matches
            except Exception:
                continue

    return matches


@tool(
    name="get_directory_tree",
    description="Generate a clean ASCII directory structure tree of the workspace with depth limits.",
    tags=["filesystem", "tree", "overview"],
)
def get_directory_tree(
    path: str = ".",
    max_depth: int = 3,
    include_files: bool = True,
) -> str:
    """
    Generate an ASCII tree diagram representing directory structure.

    Args:
        path: Target root directory relative to workspace boundary.
        max_depth: Maximum recursion depth for tree generation (defaults to 3).
        include_files: If True, lists both folders and files; if False, directories only.

    Returns:
        Formatted multi-line ASCII tree string.
    """
    resolved = resolve_safe_path(path)
    lines: List[str] = [resolved.name or "."]

    def _build(curr: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            items = sorted(
                [p for p in curr.iterdir() if p.name not in (".snapshots", ".git", "node_modules", "__pycache__")],
                key=lambda p: (0 if p.is_dir() else 1, p.name.lower()),
            )
            if not include_files:
                items = [p for p in items if p.is_dir()]

            total = len(items)
            for idx, item in enumerate(items):
                is_last = (idx == total - 1)
                connector = "└── " if is_last else "├── "
                sub_prefix = "    " if is_last else "│   "
                lines.append(f"{prefix}{connector}{item.name}{'/' if item.is_dir() else ''}")
                if item.is_dir():
                    _build(item, prefix + sub_prefix, depth + 1)
        except Exception:
            pass

    _build(resolved, "", 1)
    return "\n".join(lines)

