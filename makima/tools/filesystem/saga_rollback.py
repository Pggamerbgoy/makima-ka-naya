"""
Makima v2 — SAGA Rollback & Filesystem Snapshot Engine.
Architectural Pattern: SAGA compensating transactions with cryptographic SHA256 verification.
Zero-Hardcoding Guarantee: Fully dynamic workspace snapshot directory bound to active workspace.
Data Integrity: Strict SHA256 validation prevents silent corruption during snapshot restoration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from makima.tools.filesystem.safe_io import (
    get_workspace_dir,
    resolve_safe_path,
)
from makima.tools.registry import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class SnapshotInfo:
    """Metadata container for a single SAGA filesystem snapshot."""
    snapshot_id: str
    file_path: str
    absolute_path: str
    sha256: str
    size_bytes: int
    timestamp: float
    iso_time: str
    operation: str
    file_existed: bool
    snapshot_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SnapshotInfo:
        return cls(**data)


# ---------------------------------------------------------------------------
# SAGA Rollback Manager
# ---------------------------------------------------------------------------

class SagaRollbackManager:
    """
    Manages filesystem snapshots and SAGA compensating rollbacks.
    Snapshots are stored in a dedicated .snapshots/ directory within the workspace,
    persisting both data payloads (.snap) and JSON metadata records (.json).
    """

    _instance: Optional[SagaRollbackManager] = None
    _singleton_lock = threading.RLock()
    _counter: int = 0
    _counter_lock = threading.RLock()

    def __init__(
        self,
        workspace_dir: Optional[Path | str] = None,
        snapshots_dir: Optional[Path | str] = None,
    ):
        self._custom_workspace_dir = Path(workspace_dir).resolve() if workspace_dir else None
        self._custom_snapshots_dir = Path(snapshots_dir).resolve() if snapshots_dir else None
        self._cache: Dict[str, SnapshotInfo] = {}
        self._lock = threading.RLock()

    @property
    def workspace_dir(self) -> Path:
        """Dynamically resolved workspace directory."""
        if self._custom_workspace_dir is not None:
            return self._custom_workspace_dir
        return get_workspace_dir().resolve()

    @property
    def snapshots_dir(self) -> Path:
        """Directory housing snapshot files and metadata."""
        if self._custom_snapshots_dir is not None:
            d = self._custom_snapshots_dir
        else:
            d = self.workspace_dir / ".snapshots"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def get_instance(cls, workspace_dir: Optional[Path | str] = None) -> SagaRollbackManager:
        """Thread-safe accessor for the active SagaRollbackManager singleton."""
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = SagaRollbackManager(workspace_dir=workspace_dir)
            elif workspace_dir is not None:
                cls._instance._custom_workspace_dir = Path(workspace_dir).resolve()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Resets the singleton instance (primarily for isolated test environments)."""
        with cls._singleton_lock:
            cls._instance = None

    def _next_sequence(self) -> int:
        with self._counter_lock:
            self._counter += 1
            return self._counter

    def create_snapshot(
        self,
        file_path: Path | str,
        operation: str = "edit",
    ) -> SnapshotInfo:
        """
        Takes a snapshot of a file before a destructive operation (write, edit, delete).
        Computes SHA256 checksum and writes .snap data and .json metadata to .snapshots/.

        Args:
            file_path: File path (relative or absolute within workspace).
            operation: Name of destructive action ('edit', 'overwrite', 'delete', 'create').

        Returns:
            SnapshotInfo describing the recorded snapshot.
        """
        resolved = resolve_safe_path(file_path, self.workspace_dir)
        rel_path = str(resolved.relative_to(self.workspace_dir)).replace("\\", "/")
        now = datetime.now(timezone.utc)
        seq = self._next_sequence()

        with self._lock:
            if resolved.exists() and resolved.is_file():
                data = resolved.read_bytes()
                sha256_hash = hashlib.sha256(data).hexdigest()
                size_bytes = len(data)
                file_existed = True

                snapshot_id = f"{now.strftime('%Y%m%d_%H%M%S_%f')}_{seq:04d}_{sha256_hash[:8]}"
                snap_path = self.snapshots_dir / f"{snapshot_id}.snap"
                snap_path.write_bytes(data)
                snap_path_str = str(snap_path)
            else:
                # File did not exist (pre-creation snapshot)
                sha256_hash = ""
                size_bytes = 0
                file_existed = False
                snapshot_id = f"{now.strftime('%Y%m%d_%H%M%S_%f')}_{seq:04d}_none"
                snap_path_str = None

            info = SnapshotInfo(
                snapshot_id=snapshot_id,
                file_path=rel_path,
                absolute_path=str(resolved),
                sha256=sha256_hash,
                size_bytes=size_bytes,
                timestamp=now.timestamp(),
                iso_time=now.isoformat(),
                operation=operation,
                file_existed=file_existed,
                snapshot_path=snap_path_str,
            )

            # Persist JSON metadata record
            meta_path = self.snapshots_dir / f"{snapshot_id}.json"
            meta_path.write_text(json.dumps(info.to_dict(), indent=2), encoding="utf-8")

            # Update cache
            self._cache[snapshot_id] = info

            logger.debug(
                "Created SAGA snapshot '%s' for '%s' (operation=%s, sha256=%s)",
                snapshot_id,
                rel_path,
                operation,
                sha256_hash[:8] if sha256_hash else "none",
            )
            return info

    def _sync_snapshots_from_disk(self) -> None:
        """Discovers snapshots persisted on disk that may not be in memory cache."""
        if not self.snapshots_dir.exists():
            return

        for meta_file in self.snapshots_dir.glob("*.json"):
            snap_id = meta_file.stem
            if snap_id not in self._cache:
                try:
                    raw = json.loads(meta_file.read_text(encoding="utf-8"))
                    self._cache[snap_id] = SnapshotInfo.from_dict(raw)
                except Exception as exc:
                    logger.warning("Could not read snapshot metadata '%s': %s", meta_file, exc)

    def list_snapshots(
        self,
        file_path: Optional[Path | str] = None,
    ) -> List[SnapshotInfo]:
        """
        Lists snapshots sorted newest to oldest.

        Args:
            file_path: Optional filter for a specific file path.

        Returns:
            List of SnapshotInfo objects.
        """
        with self._lock:
            self._sync_snapshots_from_disk()
            items = list(self._cache.values())

        if file_path is not None:
            resolved = resolve_safe_path(file_path, self.workspace_dir)
            rel_path = str(resolved.relative_to(self.workspace_dir)).replace("\\", "/")
            items = [
                s for s in items
                if s.file_path == rel_path or Path(s.absolute_path).resolve() == resolved
            ]

        items.sort(key=lambda s: s.timestamp, reverse=True)
        return items

    def get_snapshot(self, snapshot_id: str) -> Optional[SnapshotInfo]:
        """Fetch a specific snapshot by its unique ID."""
        with self._lock:
            if snapshot_id in self._cache:
                return self._cache[snapshot_id]

            meta_file = self.snapshots_dir / f"{snapshot_id}.json"
            if meta_file.is_file():
                try:
                    raw = json.loads(meta_file.read_text(encoding="utf-8"))
                    info = SnapshotInfo.from_dict(raw)
                    self._cache[snapshot_id] = info
                    return info
                except Exception as exc:
                    logger.warning("Failed to parse snapshot metadata file '%s': %s", meta_file, exc)
            return None

    def rollback(
        self,
        file_path: Path | str,
        snapshot_id: Optional[str] = None,
    ) -> SnapshotInfo:
        """
        Restores a file to its state at the time of a snapshot.
        Verifies SHA256 checksums before and after restoration to guarantee zero corruption.

        Args:
            file_path: Target file path within workspace.
            snapshot_id: Specific snapshot ID to restore. If None, restores most recent snapshot.

        Returns:
            SnapshotInfo of the restored snapshot.

        Raises:
            BoundaryTraversalError: If path resolves outside workspace boundary.
            FileNotFoundError: If snapshot or data payload does not exist.
            ValueError: If SHA256 verification fails or snapshot file targets different path.
        """
        resolved = resolve_safe_path(file_path, self.workspace_dir)
        rel_path = str(resolved.relative_to(self.workspace_dir)).replace("\\", "/")

        with self._lock:
            self._sync_snapshots_from_disk()

            if snapshot_id is not None:
                info = self.get_snapshot(snapshot_id)
                if info is None:
                    raise FileNotFoundError(
                        f"SAGA snapshot '{snapshot_id}' does not exist in '{self.snapshots_dir}'."
                    )
                # Ensure snapshot matches target path
                if info.file_path != rel_path and Path(info.absolute_path).resolve() != resolved:
                    raise ValueError(
                        f"Snapshot target mismatch: snapshot '{snapshot_id}' belongs to "
                        f"'{info.file_path}', not '{rel_path}'."
                    )
            else:
                candidates = [
                    s for s in self._cache.values()
                    if s.file_path == rel_path or Path(s.absolute_path).resolve() == resolved
                ]
                if not candidates:
                    raise FileNotFoundError(
                        f"No SAGA snapshots found for file '{rel_path}'."
                    )
                candidates.sort(key=lambda s: s.timestamp, reverse=True)
                info = candidates[0]

            # Execute Rollback
            if not info.file_existed:
                # Pre-creation snapshot -> file was created after this snapshot
                if resolved.exists():
                    resolved.unlink()
                logger.info(
                    "Rolled back '%s' to pre-creation state (file removed) via snapshot '%s'",
                    rel_path,
                    info.snapshot_id,
                )
                return info

            # File existed -> restore from .snap payload
            snap_path = (
                Path(info.snapshot_path)
                if info.snapshot_path
                else self.snapshots_dir / f"{info.snapshot_id}.snap"
            )

            if not snap_path.is_file():
                raise FileNotFoundError(
                    f"Corrupted snapshot: Payload file '{snap_path}' is missing for snapshot '{info.snapshot_id}'."
                )

            data = snap_path.read_bytes()

            # Pre-restoration integrity check: verify snapshot payload SHA256
            actual_sha256 = hashlib.sha256(data).hexdigest()
            if actual_sha256 != info.sha256:
                raise ValueError(
                    f"Snapshot integrity failure: payload SHA256 ({actual_sha256}) "
                    f"does not match recorded checksum ({info.sha256})."
                )

            # Atomic write to destination
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("wb", dir=resolved.parent, delete=False) as tf:
                tf.write(data)
                temp_name = tf.name

            os.replace(temp_name, str(resolved))

            # Post-restoration integrity check: verify restored file on disk
            restored_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if restored_sha256 != info.sha256:
                raise ValueError(
                    f"Restoration verification failure: on-disk SHA256 ({restored_sha256}) "
                    f"does not match expected ({info.sha256})."
                )

            logger.info(
                "Successfully restored '%s' to snapshot '%s' (SHA256: %s)",
                rel_path,
                info.snapshot_id,
                info.sha256[:8],
            )
            return info

    def clear_snapshots(self) -> None:
        """Removes all snapshot files and purges in-memory index."""
        with self._lock:
            if self.snapshots_dir.exists():
                shutil.rmtree(self.snapshots_dir, ignore_errors=True)
                self.snapshots_dir.mkdir(parents=True, exist_ok=True)
            self._cache.clear()


# ---------------------------------------------------------------------------
# Registered Rollback Tool
# ---------------------------------------------------------------------------

@tool(
    name="rollback_file",
    description="Restores a file to its previous state using an automatic SAGA snapshot.",
    tags=["filesystem", "rollback", "saga"],
)
def rollback_file(file_path: str, snapshot_id: Optional[str] = None) -> str:
    """
    Restores a file to its previous state using an automatic SAGA snapshot.

    Args:
        file_path: Path of the file to rollback, relative to the workspace boundary.
        snapshot_id: Optional identifier of the specific snapshot to restore.
                     If omitted, restores the most recent snapshot for the file.

    Returns:
        Status confirmation detailing restored snapshot ID and verified SHA256 checksum.

    Raises:
        BoundaryTraversalError: If file_path resolves outside the workspace boundary.
        FileNotFoundError: If the snapshot or file cannot be located.
        ValueError: If SHA256 checksum verification fails.
    """
    manager = SagaRollbackManager.get_instance()
    info = manager.rollback(file_path, snapshot_id=snapshot_id)

    if not info.file_existed:
        return (
            f"Successfully rolled back '{file_path}' to pre-creation state (file removed). "
            f"Snapshot ID: {info.snapshot_id}"
        )

    return (
        f"Successfully rolled back '{file_path}' to snapshot '{info.snapshot_id}'. "
        f"Verified SHA256: {info.sha256}"
    )
