"""
Makima v2 — Windows ConPTY Interactive Terminal Wrapper.
Architectural Pattern: ConPTY Pseudo-Terminal Session with Non-Blocking I/O and Safety Guardrails.
Zero-Hardcoding Guarantee: Dynamic environment shell detection, workspace clamping, and pywinpty integration.
"""

from __future__ import annotations

import asyncio
import logging
import os

import re
import select
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from makima.core.guardrails import Guardrails, filter_secrets
from makima.tools.terminal.runner import clamp_to_workspace

logger = logging.getLogger("makima.tools.terminal.conpty")

# Try importing pywinpty directly (Rule 7: Library-first!)
try:
    import winpty
    from winpty import PtyProcess
    import winpty.enums

    PYWINPTY_AVAILABLE = True
except (ImportError, OSError):
    PYWINPTY_AVAILABLE = False
    PtyProcess = None  # type: ignore[assignment,misc]

# Regex pattern matching ANSI terminal escape sequences
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi_escapes(text: str) -> str:
    """Strips ANSI terminal escape sequences and control codes from terminal output."""
    if not text:
        return ""
    return ANSI_ESCAPE_PATTERN.sub("", text)


class ConPTYError(RuntimeError):
    """Base exception for ConPTY terminal operations."""
    pass


class ConPTYNotSupportedError(ConPTYError):
    """Raised when ConPTY is attempted on a non-Windows platform or without pywinpty."""
    pass


class ConPTYSession:
    """
    Manages an interactive Windows ConPTY pseudo-terminal session.
    Backed directly by 'winpty.PtyProcess' for native Windows console compatibility.
    """

    def __init__(
        self,
        command: Optional[str] = None,
        session_id: Optional[str] = None,
        cwd: Optional[Union[str, Path]] = None,
        dimensions: Tuple[int, int] = (24, 80),
        workspace_dir: Optional[Union[str, Path]] = None,
        guardrails: Optional[Guardrails] = None,
        auto_spawn: bool = True,
        backend: Optional[int] = None,
    ) -> None:
        """
        Initializes a ConPTY session.

        Args:
            command: Shell or executable to spawn (defaults to %COMSPEC% or cmd.exe).
            session_id: Unique identifier for the session (generated if omitted).
            cwd: Working directory (clamped within workspace).
            dimensions: Terminal dimensions as (rows, cols).
            workspace_dir: Optional custom workspace root for directory clamping.
            guardrails: Optional Guardrails instance for command validation.
            auto_spawn: Whether to spawn the PTY process immediately.
            backend: Optional backend (winpty.enums.Backend.WinPTY or ConPTY).
        """
        self.session_id = session_id or f"pty_{uuid.uuid4().hex[:8]}"
        self.command = command or os.environ.get("COMSPEC", "cmd.exe")
        self.dimensions = dimensions
        self.guardrails = guardrails or Guardrails()
        self.workspace_dir = workspace_dir
        self.cwd = clamp_to_workspace(cwd=cwd, workspace_dir=workspace_dir)
        self.backend = backend


        self._pty: Optional[PtyProcess] = None
        self._lock = threading.RLock()
        self.created_at = time.time()
        self._is_closed = False


        if auto_spawn:
            self.spawn()

    @property
    def is_alive(self) -> bool:
        """Checks if the underlying PTY process is active and running."""
        with self._lock:
            if self._is_closed or self._pty is None:
                return False
            try:
                return bool(self._pty.isalive())
            except Exception:
                return False

    @property
    def pid(self) -> Optional[int]:
        """Returns the PID of the spawned process, or None if not running."""
        if self._pty is not None:
            try:
                return self._pty.pid
            except Exception:
                return None
        return None

    @property
    def exit_code(self) -> Optional[int]:
        """Returns the exit status if terminated, else None."""
        if self._pty is not None:
            try:
                return self._pty.exitstatus
            except Exception:
                return None
        return None

    def spawn(self) -> None:
        """
        Validates safety guardrails and spawns the PTY process using pywinpty.
        """
        if not PYWINPTY_AVAILABLE or sys.platform != "win32":
            raise ConPTYNotSupportedError(
                "ConPTY interactive runner requires Windows and the 'pywinpty' library."
            )

        with self._lock:
            if self._pty is not None and self._pty.isalive():
                logger.warning("Session %s already has an active PTY process.", self.session_id)
                return

            # Intercept destructive commands before spawning
            self.guardrails.validate_command(self.command)

            rows, cols = self.dimensions
            logger.info(
                "Spawning ConPTY session '%s': command='%s', cwd='%s', dimensions=(%s, %s)",
                self.session_id,
                self.command,
                self.cwd,
                rows,
                cols,
            )

            effective_backend = self.backend
            if effective_backend is None and PYWINPTY_AVAILABLE:
                if hasattr(winpty, "Backend") and hasattr(winpty.Backend, "WinPTY"):
                    effective_backend = winpty.Backend.WinPTY
                elif hasattr(winpty, "enums") and hasattr(winpty.enums.Backend, "WinPTY"):
                    effective_backend = winpty.enums.Backend.WinPTY

            try:
                self._pty = PtyProcess.spawn(
                    argv=self.command,
                    cwd=str(self.cwd),
                    dimensions=(rows, cols),
                    backend=effective_backend,
                )
                if hasattr(self._pty, "fileobj") and hasattr(self._pty.fileobj, "settimeout"):
                    self._pty.fileobj.settimeout(0.5)
                self._is_closed = False
            except Exception:
                try:
                    self._pty = PtyProcess.spawn(
                        argv=self.command,
                        cwd=str(self.cwd),
                        dimensions=(rows, cols),
                    )
                    if hasattr(self._pty, "fileobj") and hasattr(self._pty.fileobj, "settimeout"):
                        self._pty.fileobj.settimeout(0.5)
                    self._is_closed = False
                except Exception as exc:
                    logger.error("Failed to spawn ConPTY session '%s': %s", self.session_id, exc)
                    raise ConPTYError(f"Failed to spawn ConPTY process: {exc}") from exc


    def write(self, data: str) -> None:
        """
        Writes text or escape sequences to the PTY stdin.
        """
        with self._lock:
            if not self.is_alive or self._pty is None:
                raise ConPTYError(f"Session '{self.session_id}' is not alive.")

            try:
                self._pty.write(data)
            except Exception as exc:
                logger.error("Failed writing to ConPTY session '%s': %s", self.session_id, exc)
                raise ConPTYError(f"Write error on session '{self.session_id}': {exc}") from exc

    def read(
        self,
        max_bytes: int = 4096,
        timeout: float = 0.5,
        strip_ansi: bool = False,
    ) -> str:
        """
        Reads available output from the PTY with a non-blocking timeout guard.

        Args:
            max_bytes: Maximum characters to read in this chunk.
            timeout: Maximum seconds to wait for readability.
            strip_ansi: If True, strips ANSI terminal escape codes.

        Returns:
            Decoded and sanitized string output, or empty string if no output arrived.
        """
        with self._lock:
            if self._pty is None:
                return ""

            try:
                readable, _, _ = select.select([self._pty.fileobj], [], [], max(0.0, timeout))
                if not readable:
                    return ""
                raw_data = self._pty.read(max_bytes)
            except (EOFError, OSError, TimeoutError, socket.timeout):
                return ""
            except Exception as exc:
                logger.debug("Exception reading from ConPTY session '%s': %s", self.session_id, exc)
                return ""



        # Redact secrets and handle ANSI codes
        if strip_ansi:
            raw_data = strip_ansi_escapes(raw_data)

        return filter_secrets(raw_data)

    def read_all(
        self,
        timeout: float = 0.3,
        max_iterations: int = 50,
        strip_ansi: bool = False,
    ) -> str:
        """
        Drains all currently available buffered output from the PTY.
        """
        chunks: List[str] = []
        for _ in range(max_iterations):
            chunk = self.read(max_bytes=4096, timeout=timeout, strip_ansi=strip_ansi)
            if not chunk:
                break
            chunks.append(chunk)
            # Subsequent reads use a very short timeout to drain immediately available bytes
            timeout = 0.05

        return "".join(chunks)

    def read_until(
        self,
        expected: Union[str, List[str]],
        timeout: float = 5.0,
        strip_ansi: bool = False,
        poll_interval: float = 0.1,
    ) -> str:
        """
        Continuously reads from the PTY until target token(s) are observed or timeout expires.

        Args:
            expected: Target substring or list of substrings to match.
            timeout: Maximum duration to wait in seconds.
            strip_ansi: Whether to clean ANSI sequences.
            poll_interval: Interval between select polls.

        Returns:
            The accumulated output up to and including the match.
        """
        expected_list = [expected] if isinstance(expected, str) else expected
        accumulated: List[str] = []
        start_time = time.monotonic()

        while (time.monotonic() - start_time) < timeout:
            chunk = self.read(max_bytes=4096, timeout=poll_interval, strip_ansi=strip_ansi)
            if chunk:
                accumulated.append(chunk)
                full_text = "".join(accumulated)
                for exp in expected_list:
                    if exp in full_text:
                        return full_text

            if not self.is_alive:
                break

        return "".join(accumulated)

    def resize(self, cols: int, rows: int) -> None:
        """
        Resizes the virtual console window dimensions.
        """
        with self._lock:
            if not self.is_alive or self._pty is None:
                raise ConPTYError(f"Session '{self.session_id}' is not alive.")

            try:
                self._pty.setwinsize(rows, cols)
                self.dimensions = (rows, cols)
                logger.debug("Resized ConPTY session '%s' to (%s, %s)", self.session_id, rows, cols)
            except Exception as exc:
                logger.error("Failed resizing ConPTY session '%s': %s", self.session_id, exc)
                raise ConPTYError(f"Failed to resize terminal: {exc}") from exc

    def close(self) -> Optional[int]:
        """
        Gracefully terminates and closes the PTY process.
        """
        with self._lock:
            if self._is_closed:
                return self.exit_code

            self._is_closed = True
            if self._pty is not None:

                try:
                    self._pty.close()
                except Exception as exc:
                    logger.debug("Error closing PtyProcess on session '%s': %s", self.session_id, exc)
                finally:
                    self._pty = None

            return None

    def terminate(self) -> None:
        """Alias for close()."""
        self.close()

    def __enter__(self) -> "ConPTYSession":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    async def __aenter__(self) -> "ConPTYSession":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await asyncio.to_thread(self.close)


class ConPTYManager:
    """
    Manages active ConPTY sessions across the Makima agent lifecycle.
    Thread-safe registry with automated cleanup.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, ConPTYSession] = {}
        self._lock = threading.RLock()


    def create_session(
        self,
        session_id: Optional[str] = None,
        command: Optional[str] = None,
        cwd: Optional[Union[str, Path]] = None,
        dimensions: Tuple[int, int] = (24, 80),
        workspace_dir: Optional[Union[str, Path]] = None,
    ) -> ConPTYSession:
        """Creates, registers, and spawns a new ConPTY session."""
        with self._lock:
            # Clean dead sessions
            self._prune_dead_sessions()

            session = ConPTYSession(
                command=command,
                session_id=session_id,
                cwd=cwd,
                dimensions=dimensions,
                workspace_dir=workspace_dir,
                auto_spawn=True,
            )
            self._sessions[session.session_id] = session
            return session

    def get_session(self, session_id: str) -> Optional[ConPTYSession]:
        """Retrieves an active session by identifier."""
        with self._lock:
            return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> bool:
        """Closes and removes a specific session."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is not None:
                session.close()
                return True
            return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Lists metadata of all active sessions."""
        with self._lock:
            self._prune_dead_sessions()
            return [
                {
                    "session_id": s.session_id,
                    "command": s.command,
                    "cwd": str(s.cwd),
                    "dimensions": s.dimensions,
                    "pid": s.pid,
                    "is_alive": s.is_alive,
                    "created_at": s.created_at,
                }
                for s in self._sessions.values()
            ]

    def close_all(self) -> int:
        """Closes all active sessions."""
        with self._lock:
            count = len(self._sessions)
            for session in self._sessions.values():
                session.close()
            self._sessions.clear()
            return count

    def _prune_dead_sessions(self) -> None:
        """Internal helper to clean up terminated sessions."""
        dead_keys = [k for k, s in self._sessions.items() if not s.is_alive]
        for k in dead_keys:
            sess = self._sessions.pop(k, None)
            if sess:
                sess.close()


# Module-level singleton
_conpty_manager_instance: Optional[ConPTYManager] = None
_manager_lock = threading.Lock()


def get_conpty_manager() -> ConPTYManager:
    """Returns the singleton ConPTYManager instance."""
    global _conpty_manager_instance
    if _conpty_manager_instance is None:
        with _manager_lock:
            if _conpty_manager_instance is None:
                _conpty_manager_instance = ConPTYManager()
    return _conpty_manager_instance
