"""
Makima v2 — Safe Filesystem & SAGA Rollback Toolset.
Architectural Pattern: Hermes-style safe filesystem tools with strict boundary clamping and cryptographic SAGA rollback.
Zero-Hardcoding Guarantee: Fully dynamic workspace path resolution via MakimaConfig with thread-safe overrides.
"""

from __future__ import annotations

from makima.tools.filesystem.safe_io import (
    BoundaryTraversalError,
    delete_file,
    edit_file,
    get_workspace_dir,
    list_directory,
    read_file,
    resolve_safe_path,
    set_workspace_dir,
    write_file,
)
from makima.tools.filesystem.saga_rollback import (
    SagaRollbackManager,
    SnapshotInfo,
    rollback_file,
)

__all__ = [
    # Tools
    "read_file",
    "write_file",
    "edit_file",
    "delete_file",
    "list_directory",
    "rollback_file",
    # SAGA Manager & Models
    "SagaRollbackManager",
    "SnapshotInfo",
    # Security & Resolution Helpers
    "BoundaryTraversalError",
    "get_workspace_dir",
    "set_workspace_dir",
    "resolve_safe_path",
]
