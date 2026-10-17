"""
Makima v2 — Structured Runtime Telemetry (Step 24).
Architectural Pattern: In-process lightweight event emitter.
Zero external dependencies — stdlib only (json, pathlib, time, asyncio, logging).

Design:
- JSONL append-only log at ~/.makima/state/telemetry.jsonl (one JSON object per line).
- Daily file rotation: telemetry_2026-09-30.jsonl
- Event types: engine.turn_start, engine.turn_end, provider.request, provider.response,
               tool.execute, tool.error, tool.blocked
- get_recent(n) returns last N events for /api/telemetry endpoint.
- Thread-safe via asyncio.Lock (async context) and simple file append (atomic on POSIX, fine on Windows).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("makima.core.telemetry")

# Module-level singleton
_TELEMETRY: Optional["StructuredTelemetry"] = None


def get_telemetry() -> "StructuredTelemetry":
    """Returns the module-level telemetry singleton, creating it on first call."""
    global _TELEMETRY
    if _TELEMETRY is None:
        _TELEMETRY = StructuredTelemetry()
    return _TELEMETRY


class TelemetryEvent:
    """One structured telemetry event."""

    __slots__ = ("event_type", "timestamp", "data")

    def __init__(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        self.event_type = event_type
        self.timestamp = time.time()
        self.data: Dict[str, Any] = data or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event_type,
            "ts": self.timestamp,
            "ts_iso": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            **self.data,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class StructuredTelemetry:
    """
    Lightweight in-process telemetry emitter.
    Events are written to a daily-rotated JSONL file and kept in an in-memory ring buffer.

    Usage:
        tel = get_telemetry()
        await tel.emit("tool.execute", {"tool": "web_search", "latency_ms": 123})
        recent = tel.get_recent(50)
    """

    DEFAULT_BUFFER_SIZE = 500  # in-memory ring buffer capacity

    def __init__(
        self,
        log_dir: Optional[Union[Path, str]] = None,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        enabled: bool = True,
    ) -> None:
        if log_dir is None:
            try:
                from makima.config import get_settings
                log_dir = Path(get_settings().sqlite_db_path).parent
            except Exception:
                log_dir = Path.home() / ".makima" / "state"

        self.log_dir = Path(log_dir)
        self.buffer_size = buffer_size
        self.enabled = enabled

        self._buffer: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._current_date: str = ""
        self._log_file: Optional[Path] = None

    def _get_log_file(self) -> Path:
        """Returns today's log file path, updating on date change."""
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_date:
            self._current_date = today
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._log_file = self.log_dir / f"telemetry_{today}.jsonl"
        return self._log_file  # type: ignore[return-value]

    async def emit(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Emits a telemetry event.
        Non-blocking: file write is done in a thread to avoid blocking the event loop.
        """
        if not self.enabled:
            return

        event = TelemetryEvent(event_type, data)
        event_dict = event.to_dict()
        jsonl_line = event.to_jsonl()

        async with self._lock:
            # Add to ring buffer
            self._buffer.append(event_dict)
            if len(self._buffer) > self.buffer_size:
                self._buffer = self._buffer[-self.buffer_size :]

        # Write to JSONL file in thread (non-blocking)
        log_file = self._get_log_file()
        try:
            await asyncio.to_thread(_append_jsonl, log_file, jsonl_line)
        except Exception as e:
            logger.debug(f"Telemetry file write failed (non-critical): {e}")

    def emit_sync(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Synchronous emit for use in non-async contexts.
        File write is skipped (buffer-only) to avoid blocking.
        """
        if not self.enabled:
            return
        event = TelemetryEvent(event_type, data)
        self._buffer.append(event.to_dict())
        if len(self._buffer) > self.buffer_size:
            self._buffer = self._buffer[-self.buffer_size :]

    def get_recent(self, n: int = 50) -> List[Dict[str, Any]]:
        """Returns the last N events from the in-memory buffer (newest last)."""
        return list(self._buffer[-n:])

    def get_event_count(self) -> int:
        """Returns the number of events currently in the buffer."""
        return len(self._buffer)

    def clear(self) -> None:
        """Clears the in-memory buffer (does not delete log files)."""
        self._buffer.clear()


def _append_jsonl(path: Path, line: str) -> None:
    """Synchronous JSONL append — run in a thread via asyncio.to_thread."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
