"""
Makima Sentinel — Event-Driven Autonomous Daemon ("The Listening Devil").
Architectural Pattern: Zero-Token Reactive Observer & Event Dispatcher.

Features:
1. File System Hook: Watchdog observer monitoring Downloads and project folders for archives (.zip, .exe)
   and crash logs (*crash*.log, *error*.log) with size stabilization debouncing.
2. Clipboard & Window Hook: Ultra-low-overhead Win32 clipboard sequence listener detecting copied
   code stack traces (Python, JS/TS, Rust, Go, Java) alongside the active editor window.
3. System Resource Hook: psutil threshold watcher detecting extreme RAM consumption (>90%) and
   runaway runaway/zombie processes with per-process cooldown suppression.
4. Autonomous Decision Supervisor: Integrated DND gate, anti-fatigue cooldowns, brain consultation,
   and interactive Windows Action Center toast alerts with one-click resolution actions.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import psutil
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger("makima.sentinel.event_daemon")

# ---------------------------------------------------------------------------
# Constants & Defaults
# ---------------------------------------------------------------------------
DEFAULT_RAM_THRESHOLD_PCT = 90.0
DEFAULT_CPU_THRESHOLD_PCT = 85.0
DEFAULT_PROCESS_RAM_MB = 3000.0  # 3 GB
DEFAULT_ERROR_COOLDOWN_S = 60.0  # 1 min cooldown between duplicate error alerts
DEFAULT_RESOURCE_COOLDOWN_S = 900.0  # 15 min cooldown per offending process
DEFAULT_DOWNLOAD_COOLDOWN_S = 180.0  # 3 min cooldown
CLIPBOARD_CHECK_INTERVAL_S = 0.25  # 250ms check
RESOURCE_CHECK_INTERVAL_S = 10.0  # 10s check
BRAIN_URL = "http://127.0.0.1:8000"

# Target extensions for download monitoring
ARCHIVE_EXTENSIONS = {
    ".zip", ".tar.gz", ".tar.bz2", ".tgz", ".7z", ".rar",
    ".exe", ".msi", ".iso", ".dmg", ".pkg"
}
# Temporary extensions to ignore
TEMP_EXTENSIONS = {
    ".tmp", ".crdownload", ".part", ".download", ".opdownload",
    ".partial", ".swp", ".~"
}

# Known password managers and credential vaults to ignore for clipboard privacy
BLOCKED_SENSITIVE_PROCESSES = {
    "1password.exe",
    "bitwarden.exe",
    "keepass.exe",
    "keepassxc.exe",
    "lastpass.exe",
    "authy.exe",
    "dashlane.exe",
    "credentialuibroker.exe",
}


# ---------------------------------------------------------------------------
# 1. Stack Trace Analyzer
# ---------------------------------------------------------------------------

@dataclass
class StackTraceInfo:
    """Structured information extracted from a detected code error/traceback."""
    language: str
    error_type: str
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    raw_text: str = ""

    def summary(self) -> str:
        loc = f" at {Path(self.file_path).name}:{self.line_number}" if self.file_path and self.line_number else ""
        return f"{self.error_type}: {self.message}{loc}".strip()


class StackTraceAnalyzer:
    """
    Regex and heuristic parser identifying code exceptions and stack traces
    copied to the system clipboard across major programming ecosystems.
    """

    # Python Patterns
    PY_TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE)
    PY_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)(?:, in (\w+))?')
    PY_ERROR_RE = re.compile(
        r"^(?:[\w\.]+\.)?([A-Za-z0-9_]*(?:Error|Exception|Warning|Exit|Interrupt|Fault)): (.*)$",
        re.MULTILINE
    )

    # JavaScript / TypeScript / Node.js Patterns
    JS_ERROR_RE = re.compile(
        r"^(?:Uncaught )?([A-Za-z0-9_]*(?:Error|Exception)): (.*)$",
        re.MULTILINE
    )
    JS_FRAME_RE = re.compile(r"^\s*at (?:(.*?) \()?([^:]+):(\d+):(\d+)\)?", re.MULTILINE)

    # Rust Panic Patterns
    RUST_PANIC_RE = re.compile(r"thread '([^']+)' panicked at (?:'([^']+)', )?([^:]+):(\d+)")
    RUST_BACKTRACE_RE = re.compile(r"stack backtrace:\s*\n\s*0:", re.MULTILINE)

    # Go Panic Patterns
    GO_PANIC_RE = re.compile(r"panic: (.*?)\n\ngoroutine \d+ \[running\]:", re.DOTALL)

    # Java / JVM Patterns
    JAVA_EXCEPTION_RE = re.compile(r"Exception in thread \"[^\"]+\" ([\w\.]+Exception): (.*)")
    JAVA_FRAME_RE = re.compile(r"^\s*at ([\w\.\$]+)\(([\w\.]+):(\d+)\)", re.MULTILINE)

    # General / C++ Faults
    GENERIC_FAULT_RE = re.compile(
        r"(Segmentation fault|SIGSEGV|core dumped|Assertion `(.*?)` failed|FATAL ERROR: (.*))",
        re.IGNORECASE
    )

    @classmethod
    def detect(cls, text: str) -> Optional[StackTraceInfo]:
        """
        Analyzes plain text to determine if it contains an active code stack trace.
        Returns a StackTraceInfo object if detected, or None if ordinary text.
        """
        if not text or len(text.strip()) < 25:
            return None

        # Clamp max text size to analyze to avoid catastrophic backtracking
        sample = text[:15000].strip()

        # 1. Check Python Traceback
        if cls.PY_TRACEBACK_RE.search(sample):
            frames = list(cls.PY_FRAME_RE.finditer(sample))
            last_file, last_line = None, None
            if frames:
                last_file = frames[-1].group(1)
                try:
                    last_line = int(frames[-1].group(2))
                except ValueError:
                    pass

            error_match = cls.PY_ERROR_RE.search(sample)
            err_type = error_match.group(1) if error_match else "PythonError"
            err_msg = error_match.group(2) if error_match else "Exception encountered in Python runtime"

            return StackTraceInfo(
                language="Python",
                error_type=err_type,
                message=err_msg.strip(),
                file_path=last_file,
                line_number=last_line,
                raw_text=sample,
            )

        # 2. Check JavaScript / TypeScript / Node.js Error
        js_match = cls.JS_ERROR_RE.search(sample)
        js_frames = list(cls.JS_FRAME_RE.finditer(sample))
        if js_match and js_frames:
            err_type = js_match.group(1)
            err_msg = js_match.group(2)
            first_frame = js_frames[0]
            fpath = first_frame.group(2)
            try:
                fline = int(first_frame.group(3))
            except (ValueError, IndexError):
                fline = None

            return StackTraceInfo(
                language="JavaScript",
                error_type=err_type,
                message=err_msg.strip(),
                file_path=fpath,
                line_number=fline,
                raw_text=sample,
            )

        # 3. Check Rust Panic
        rust_match = cls.RUST_PANIC_RE.search(sample)
        if rust_match or cls.RUST_BACKTRACE_RE.search(sample):
            msg = rust_match.group(2) if rust_match and rust_match.group(2) else "Explicit panic or backtrace"
            fpath = rust_match.group(3) if rust_match else None
            fline = int(rust_match.group(4)) if rust_match and rust_match.group(4) else None
            return StackTraceInfo(
                language="Rust",
                error_type="Panic",
                message=msg.strip(),
                file_path=fpath,
                line_number=fline,
                raw_text=sample,
            )

        # 4. Check Go Panic
        go_match = cls.GO_PANIC_RE.search(sample)
        if go_match:
            return StackTraceInfo(
                language="Go",
                error_type="Panic",
                message=go_match.group(1).strip()[:120],
                raw_text=sample,
            )

        # 5. Check Java / Kotlin Exception
        java_match = cls.JAVA_EXCEPTION_RE.search(sample)
        java_frames = list(cls.JAVA_FRAME_RE.finditer(sample))
        if java_match or (java_frames and "Exception" in sample):
            err_type = java_match.group(1) if java_match else "JavaException"
            err_msg = java_match.group(2) if java_match else "Unhandled JVM exception"
            fpath = java_frames[0].group(2) if java_frames else None
            fline = int(java_frames[0].group(3)) if java_frames else None
            return StackTraceInfo(
                language="Java",
                error_type=err_type,
                message=err_msg.strip(),
                file_path=fpath,
                line_number=fline,
                raw_text=sample,
            )

        # 6. Check Generic / C++ Fault
        fault_match = cls.GENERIC_FAULT_RE.search(sample)
        if fault_match and ("stack" in sample.lower() or "error" in sample.lower()):
            return StackTraceInfo(
                language="Native",
                error_type="FatalFault",
                message=fault_match.group(1).strip(),
                raw_text=sample,
            )

        return None


# ---------------------------------------------------------------------------
# 2. Clipboard & Window Hook
# ---------------------------------------------------------------------------

class ClipboardEventWatcher:
    """
    Ultra-lightweight background thread that uses the Win32 GetClipboardSequenceNumber
    API (0.00% CPU overhead) to detect clipboard changes in real time and evaluate them
    for copied error stack traces.
    """

    def __init__(
        self,
        on_stack_trace: Callable[[StackTraceInfo, Dict[str, Any]], None],
        on_clipboard_text: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        check_interval_s: float = CLIPBOARD_CHECK_INTERVAL_S,
    ):
        self.on_stack_trace = on_stack_trace
        self.on_clipboard_text = on_clipboard_text
        self.check_interval_s = check_interval_s
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_seq = 0
        self._last_content_hash = ""

    def start(self) -> None:
        """Starts the clipboard polling worker thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        # Initialize sequence
        self._last_seq = self._get_sequence_number()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="sentinel-clipboard-watcher",
            daemon=True,
        )
        self._thread.start()
        logger.debug("ClipboardEventWatcher started.")

    def stop(self) -> None:
        """Stops the clipboard worker thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.debug("ClipboardEventWatcher stopped.")

    def _get_sequence_number(self) -> int:
        """Retrieves the current clipboard sequence number from user32.dll."""
        try:
            return int(ctypes.windll.user32.GetClipboardSequenceNumber())
        except Exception:
            return 0

    def _read_clipboard_text(self) -> Optional[str]:
        """Safely reads Unicode text from the Windows clipboard with retry."""
        import win32clipboard
        import win32con

        for _ in range(3):
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                        return str(data) if data else None
                    return None
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                time.sleep(0.02)
        return None

    def _worker_loop(self) -> None:
        """Continuous listener loop."""
        from makima.sentinel.observer import _get_active_window

        while not self._stop_event.is_set():
            try:
                curr_seq = self._get_sequence_number()
                if curr_seq != self._last_seq and curr_seq != 0:
                    self._last_seq = curr_seq

                    # Security gate: Do not touch clipboard if user is in a password manager
                    active_win = _get_active_window()
                    proc_name = (active_win.get("process") or "").lower()
                    if proc_name in BLOCKED_SENSITIVE_PROCESSES:
                        logger.debug("Clipboard read skipped: Active window is sensitive password manager (%s)", proc_name)
                    else:
                        text = self._read_clipboard_text()
                        if text and len(text.strip()) >= 15:
                            content_hash = str(hash(text[:500]))
                            if content_hash != self._last_content_hash:
                                self._last_content_hash = content_hash
                                trace_info = StackTraceAnalyzer.detect(text)
                                if trace_info:
                                    logger.info(
                                        "Clipboard stack trace detected: [%s] %s in %s",
                                        trace_info.language,
                                        trace_info.error_type,
                                        active_win.get("process", "unknown"),
                                    )
                                    self.on_stack_trace(trace_info, active_win)
                                elif self.on_clipboard_text:
                                    self.on_clipboard_text(text, active_win)
            except Exception as exc:
                logger.debug("Error in clipboard watcher loop: %s", exc)

            self._stop_event.wait(self.check_interval_s)


# ---------------------------------------------------------------------------
# 3. File System Hook (Watchdog)
# ---------------------------------------------------------------------------

@dataclass
class FileAlertEvent:
    """Event container for significant filesystem events (downloads, crash logs)."""
    event_type: str  # 'archive_download', 'installer_download', 'crash_log'
    path: Path
    filename: str
    size_bytes: int
    extension: str

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 2)


class _DownloadsEventHandler(FileSystemEventHandler):
    """Watchdog event handler filtering for complete downloads and crash logs."""

    def __init__(self, callback: Callable[[FileAlertEvent], None]):
        super().__init__()
        self.callback = callback
        self._recently_handled: Set[str] = set()
        self._lock = threading.Lock()

    def _is_temp(self, path: Path) -> bool:
        name = path.name.lower()
        if name.startswith("~$") or name.startswith("."):
            return True
        for ext in TEMP_EXTENSIONS:
            if name.endswith(ext):
                return True
        return False

    def _classify_event(self, path: Path) -> Optional[str]:
        name = path.name.lower()
        if "crash" in name or "error" in name:
            if name.endswith(".log") or name.endswith(".txt") or name.endswith(".traceback"):
                return "crash_log"

        if name.endswith(".exe") or name.endswith(".msi"):
            return "installer_download"

        for ext in ARCHIVE_EXTENSIONS:
            if name.endswith(ext):
                return "archive_download"

        return None

    def _debounce_and_dispatch(self, file_path_str: str) -> None:
        """Ensures file write has stabilized before dispatching alert."""
        path = Path(file_path_str)
        if not path.is_file() or self._is_temp(path):
            return

        cat = self._classify_event(path)
        if not cat:
            return

        with self._lock:
            if str(path) in self._recently_handled:
                return
            self._recently_handled.add(str(path))

        # Size stabilization check (wait up to 3s for download completion)
        prev_size = -1
        stable = False
        for _ in range(4):
            time.sleep(0.5)
            if not path.exists():
                return
            try:
                curr_size = path.stat().st_size
                if curr_size > 0 and curr_size == prev_size:
                    stable = True
                    break
                prev_size = curr_size
            except Exception:
                break

        if stable and path.exists():
            try:
                size = path.stat().st_size
                event = FileAlertEvent(
                    event_type=cat,
                    path=path,
                    filename=path.name,
                    size_bytes=size,
                    extension=path.suffix.lower(),
                )
                self.callback(event)
            except Exception as exc:
                logger.debug("Failed to dispatch file alert for %s: %s", path, exc)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            threading.Thread(
                target=self._debounce_and_dispatch,
                args=(event.src_path,),
                daemon=True,
            ).start()

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            threading.Thread(
                target=self._debounce_and_dispatch,
                args=(event.src_path,),
                daemon=True,
            ).start()


class FileSystemWatcher:
    """
    Watchdog observer supervisor monitoring Downloads and project directories.
    """

    def __init__(
        self,
        on_file_alert: Callable[[FileAlertEvent], None],
        monitored_paths: Optional[List[Path | str]] = None,
    ):
        self.on_file_alert = on_file_alert
        self.monitored_paths = monitored_paths or self._default_monitored_paths()
        self._observer: Optional[Observer] = None
        self._handler = _DownloadsEventHandler(self.on_file_alert)

    def _default_monitored_paths(self) -> List[Path]:
        paths = []
        downloads = Path.home() / "Downloads"
        if downloads.exists():
            paths.append(downloads)
        return paths

    def start(self) -> None:
        """Starts watchdog background observer threads."""
        if self._observer and self._observer.is_alive():
            return
        self._observer = Observer()
        valid_count = 0
        for p in self.monitored_paths:
            path_obj = Path(p).expanduser().resolve()
            if path_obj.exists() and path_obj.is_dir():
                self._observer.schedule(self._handler, str(path_obj), recursive=False)
                valid_count += 1
                logger.debug("FileSystemWatcher monitoring: %s", path_obj)

        if valid_count > 0:
            self._observer.start()
            logger.info("FileSystemWatcher started on %d directory path(s).", valid_count)
        else:
            logger.debug("FileSystemWatcher: No valid directories to monitor.")

    def stop(self) -> None:
        """Stops watchdog observer threads."""
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception as exc:
                logger.debug("Error stopping FileSystemWatcher: %s", exc)
        logger.debug("FileSystemWatcher stopped.")


# ---------------------------------------------------------------------------
# 4. System Resource Hook (psutil)
# ---------------------------------------------------------------------------

@dataclass
class ResourceAlertEvent:
    """Event container for abnormal system resource conditions."""
    alert_type: str  # 'high_ram', 'runaway_cpu', 'zombie_process'
    pid: int
    process_name: str
    memory_mb: float
    cpu_percent: float
    system_ram_percent: float


class SystemResourceWatcher:
    """
    Background daemon monitoring system RAM and process CPU consumption.
    Dispatches alerts with per-process anti-spam cooldowns.
    """

    def __init__(
        self,
        on_resource_alert: Callable[[ResourceAlertEvent], None],
        ram_threshold_pct: float = DEFAULT_RAM_THRESHOLD_PCT,
        cpu_threshold_pct: float = DEFAULT_CPU_THRESHOLD_PCT,
        check_interval_s: float = RESOURCE_CHECK_INTERVAL_S,
        cooldown_s: float = DEFAULT_RESOURCE_COOLDOWN_S,
    ):
        self.on_resource_alert = on_resource_alert
        self.ram_threshold_pct = ram_threshold_pct
        self.cpu_threshold_pct = cpu_threshold_pct
        self.check_interval_s = check_interval_s
        self.cooldown_s = cooldown_s

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cooldowns: Dict[int, float] = {}  # PID -> last alert timestamp
        self._lock = threading.Lock()

    def start(self) -> None:
        """Starts resource watcher loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="sentinel-resource-watcher",
            daemon=True,
        )
        self._thread.start()
        logger.debug("SystemResourceWatcher started.")

    def stop(self) -> None:
        """Stops resource watcher loop."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.debug("SystemResourceWatcher stopped.")

    def _is_cooldown_active(self, pid: int, now: float) -> bool:
        with self._lock:
            last = self._cooldowns.get(pid, 0.0)
            if now - last < self.cooldown_s:
                return True
            self._cooldowns[pid] = now
            return False

    def _worker_loop(self) -> None:
        """Periodic hardware evaluation loop."""
        while not self._stop_event.is_set():
            try:
                now = time.time()
                mem = psutil.virtual_memory()
                ram_pct = mem.percent

                # 1. High RAM condition check
                if ram_pct >= self.ram_threshold_pct:
                    # Identify the most RAM-hungry process
                    top_proc: Optional[psutil.Process] = None
                    max_rss = 0
                    for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
                        try:
                            info = p.info
                            m_info = info.get("memory_info")
                            rss = m_info.rss if m_info else 0
                            if rss > max_rss:
                                max_rss = rss
                                top_proc = p
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

                    if top_proc and max_rss > 100 * 1024 * 1024:  # > 100MB
                        pid = top_proc.pid
                        if not self._is_cooldown_active(pid, now):
                            rss_mb = round(max_rss / (1024 * 1024), 1)
                            cpu_val = round(top_proc.info.get("cpu_percent") or 0.0, 1)
                            pname = top_proc.info.get("name") or f"PID {pid}"
                            event = ResourceAlertEvent(
                                alert_type="high_ram",
                                pid=pid,
                                process_name=pname,
                                memory_mb=rss_mb,
                                cpu_percent=cpu_val,
                                system_ram_percent=ram_pct,
                            )
                            self.on_resource_alert(event)

                # 2. Runaway CPU process check
                else:
                    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
                        try:
                            info = p.info
                            cpu_val = float(info.get("cpu_percent") or 0.0)
                            if cpu_val >= self.cpu_threshold_pct and p.pid not in (0, 4):
                                pid = p.pid
                                if not self._is_cooldown_active(pid, now):
                                    m_info = info.get("memory_info")
                                    rss_mb = round((m_info.rss if m_info else 0) / (1024 * 1024), 1)
                                    pname = info.get("name") or f"PID {pid}"
                                    event = ResourceAlertEvent(
                                        alert_type="runaway_cpu",
                                        pid=pid,
                                        process_name=pname,
                                        memory_mb=rss_mb,
                                        cpu_percent=cpu_val,
                                        system_ram_percent=ram_pct,
                                    )
                                    self.on_resource_alert(event)
                                    break
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

            except Exception as exc:
                logger.debug("Error in resource watcher loop: %s", exc)

            self._stop_event.wait(self.check_interval_s)


_GLOBAL_SENTINEL_DAEMON: Optional[SentinelEventDaemon] = None


def get_sentinel_daemon() -> Optional[SentinelEventDaemon]:
    """Returns the globally active SentinelEventDaemon instance, if started."""
    return _GLOBAL_SENTINEL_DAEMON


# ---------------------------------------------------------------------------
# 5. Master Event-Driven Autonomous Daemon Supervisor
# ---------------------------------------------------------------------------

class SentinelEventDaemon:
    """
    Master supervisor coordinating the reactive OS watchers ("The Listening Devil"):
    1. Clipboard & Window Hook (error stack traces)
    2. File System Hook (Downloads & crash logs)
    3. System Resource Hook (RAM spikes & runaway processes)
    Enforces DND gates, anti-fatigue cooldowns, and actionable Windows notifications.
    """

    def __init__(
        self,
        monitored_paths: Optional[List[Path | str]] = None,
        ram_threshold_pct: float = DEFAULT_RAM_THRESHOLD_PCT,
        cpu_threshold_pct: float = DEFAULT_CPU_THRESHOLD_PCT,
    ):
        self.ram_threshold_pct = ram_threshold_pct
        self.cpu_threshold_pct = cpu_threshold_pct

        self._clipboard_watcher = ClipboardEventWatcher(
            on_stack_trace=self._handle_stack_trace,
            on_clipboard_text=self._handle_clipboard_text,
        )
        self._fs_watcher = FileSystemWatcher(
            on_file_alert=self._handle_file_alert,
            monitored_paths=monitored_paths,
        )
        self._resource_watcher = SystemResourceWatcher(
            on_resource_alert=self._handle_resource_alert,
            ram_threshold_pct=ram_threshold_pct,
            cpu_threshold_pct=cpu_threshold_pct,
        )

        self._is_running = False
        self._last_alert_ts: Dict[str, float] = {}  # category -> timestamp
        self._lock = threading.Lock()
        self._live_dispatcher: Optional[Callable[[str], Any]] = None
        self._live_loop: Optional[Any] = None

    def set_live_dispatcher(
        self,
        dispatcher_fn: Optional[Callable[[str], Any]],
        loop: Optional[Any] = None,
    ) -> None:
        """Registers a live session callback (e.g. GeminiLiveSession.send_text_prompt)."""
        self._live_dispatcher = dispatcher_fn
        self._live_loop = loop
        logger.info("Sentinel live session dispatcher registered.")

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        """Starts all reactive watchers simultaneously."""
        if self._is_running:
            return
        global _GLOBAL_SENTINEL_DAEMON
        _GLOBAL_SENTINEL_DAEMON = self
        self._is_running = True
        self._clipboard_watcher.start()
        self._fs_watcher.start()
        self._resource_watcher.start()
        logger.info("The Listening Devil (Sentinel Event-Driven Daemon) is fully active.")

    def stop(self) -> None:
        """Stops all reactive watchers cleanly."""
        if not self._is_running:
            return
        global _GLOBAL_SENTINEL_DAEMON
        if _GLOBAL_SENTINEL_DAEMON is self:
            _GLOBAL_SENTINEL_DAEMON = None
        self._clipboard_watcher.stop()
        self._fs_watcher.stop()
        self._resource_watcher.stop()
        self._is_running = False
        logger.info("The Listening Devil (Sentinel Event-Driven Daemon) stopped.")

    # -----------------------------------------------------------------------
    # Decision Gate Checks
    # -----------------------------------------------------------------------

    def _check_dnd(self) -> bool:
        """Suppresses notifications if user is playing games or in fullscreen."""
        if os.getenv("MAKIMA_HEADLESS_TEST") == "true":
            return False
        from makima.sentinel.observer import _get_active_window, is_dnd_process
        win = _get_active_window()
        proc = win.get("process", "")
        if is_dnd_process(proc):
            logger.debug("Listening Devil: DND active (process: %s)", proc)
            return True
        return False

    def _check_cooldown(self, category: str, cooldown_s: float) -> bool:
        """Returns True if category is currently under cooldown."""
        with self._lock:
            now = time.time()
            last = self._last_alert_ts.get(category, 0.0)
            if now - last < cooldown_s:
                return True
            self._last_alert_ts[category] = now
            return False

    # -----------------------------------------------------------------------
    # Event Handlers
    # -----------------------------------------------------------------------

    def _handle_stack_trace(self, trace_info: StackTraceInfo, active_win: Dict[str, Any]) -> None:
        """Fires when user copies a code stack trace or error to the clipboard."""
        if self._check_dnd():
            return

        cat_key = f"trace_{trace_info.error_type}"
        if self._check_cooldown(cat_key, DEFAULT_ERROR_COOLDOWN_S):
            return

        app_name = active_win.get("process") or "Code Editor"
        title = f"Makima Sentinel ⚠️ {trace_info.language} Error"
        summary = trace_info.summary()
        body = f"[{app_name}] {summary}\nKya main error diagnose karke fix generate kar doon?"

        logger.info("Proactively dispatching stack-trace alert for: %s", summary)

        def _on_action(action_str: str):
            clean = (action_str or "").lower()
            if "fix" in clean or "haan" in clean:
                logger.info("User requested autonomous fix for error: %s", summary)
                # Dispatch background fix request to Makima brain API with DLP masking
                from makima.sentinel.observer import mask_sensitive_data
                masked_trace = mask_sensitive_data(trace_info.raw_text)
                self._dispatch_brain_task(
                    f"Copied error from {app_name}:\n{masked_trace}\n\nDiagnose root cause and provide concise fix."
                )

        self._show_toast(
            title=title,
            body=body,
            buttons=["Haan, Fix Karo", "Abhi Nahi"],
            callback=_on_action,
        )

        # Priority #1: Live Stream Dispatch (Gemini 3.8 Live)
        if self._live_dispatcher:
            try:
                from makima.core.guardrails import mask_sensitive_data
                clean_trace = mask_sensitive_data(trace_info.raw_text[:600])
                prompt = (
                    f"[SYSTEM_EVENT]: Source: Code Stack Trace. Language: {trace_info.language}. "
                    f"Error: {trace_info.summary()}. App: {app_name}. Trace snippet: \"\"\"{clean_trace}\"\"\". "
                    "Proactively notify the user via a brief spoken 1-sentence voice update and offer to diagnose and fix."
                )
                self._dispatch_live_event(prompt)
            except Exception as exc:
                logger.debug("Failed dispatching trace to live session: %s", exc)

    def _handle_clipboard_text(self, text: str, active_win: Dict[str, Any]) -> None:
        """Dispatches sanitized ambient clipboard text to Gemini Live for semantic evaluation."""
        if not self._live_dispatcher:
            return
        if self._check_dnd():
            return

        # Debounce duplicate clipboard text pushes within 5s
        if self._check_cooldown("live_clip_text", 5.0):
            return

        from makima.core.guardrails import mask_sensitive_data
        sanitized = mask_sensitive_data(text.strip())
        if not sanitized or len(sanitized) < 10:
            return

        app_name = active_win.get("process") or "Active Window"
        prompt = (
            f"[SYSTEM_EVENT]: Source: Windows Clipboard. Active App: {app_name}. "
            f"Content: \"\"\"{sanitized[:500]}\"\"\". "
            "Evaluate user intent. If actionable (courier tracking, downloaded bill, meeting, error, tasks), "
            "proactively assist or call tools. If trivial or non-actionable, remain completely silent."
        )
        self._dispatch_live_event(prompt)

    def _handle_file_alert(self, event: FileAlertEvent) -> None:
        """Fires when significant archive/installer or crash log arrives on disk."""
        if self._check_dnd():
            return

        if self._check_cooldown("file_alert", DEFAULT_DOWNLOAD_COOLDOWN_S):
            return

        if event.event_type == "crash_log":
            title = "Makima Sentinel 💥 Crash Log Detected"
            body = f"Crash file '{event.filename}' created. Kya main iska traceback inspect karoon?"
            btn_text = "Inspect Log"
        else:
            title = "Makima Sentinel 📦 Download Complete"
            body = f"Downloaded '{event.filename}' ({event.size_mb:.1f} MB). Kya ise explore ya workspace me move kar doon?"
            btn_text = "Open Folder"

        logger.info("Proactively dispatching file alert for: %s", event.filename)

        def _on_action(action_str: str):
            clean = (action_str or "").lower()
            if "open" in clean or "inspect" in clean:
                try:
                    subprocess.Popen(["explorer", f"/select,{str(event.path)}"])
                except Exception as exc:
                    logger.warning("Could not open explorer: %s", exc)

        self._show_toast(
            title=title,
            body=body,
            buttons=[btn_text, "Dismiss"],
            callback=_on_action,
        )

        # Priority #1: Live Stream Dispatch (Gemini 3.8 Live)
        if self._live_dispatcher:
            prompt = (
                f"[SYSTEM_EVENT]: Source: File System. Event Type: {event.event_type}. "
                f"File: '{event.filename}' ({event.size_mb:.1f} MB). Path: '{event.path}'. "
                "Evaluate if this download requires proactive action (e.g. organizing, inspecting crash log). "
                "If non-actionable, remain completely silent."
            )
            self._dispatch_live_event(prompt)

    def _handle_resource_alert(self, event: ResourceAlertEvent) -> None:
        """Fires when system RAM or a single process CPU exceeds safety thresholds."""
        if self._check_dnd():
            return

        if event.alert_type == "high_ram":
            title = "Makima Sentinel 🛑 High RAM Alert"
            body = (
                f"System RAM {event.system_ram_percent:.0f}%! {event.process_name} (PID {event.pid}) "
                f"is consuming {event.memory_mb:.0f} MB RAM. Kill kar doon?"
            )
        else:
            title = "Makima Sentinel ⚡ Runaway CPU Alert"
            body = (
                f"{event.process_name} (PID {event.pid}) is using {event.cpu_percent:.0f}% CPU! "
                f"Kya ise kill kar doon?"
            )

        logger.info("Proactively dispatching resource alert for PID %d (%s)", event.pid, event.process_name)

        def _on_action(action_str: str):
            clean = (action_str or "").lower()
            if "kill" in clean:
                from makima.tools.os.processes import terminate_process
                res = terminate_process(pid=event.pid, force=True)
                logger.info("Terminated process PID %d: %s", event.pid, res)

        self._show_toast(
            title=title,
            body=body,
            buttons=["Kill Process", "Dismiss"],
            callback=_on_action,
        )

        # Priority #1: Live Stream Dispatch (Gemini 3.8 Live)
        if self._live_dispatcher:
            prompt = (
                f"[SYSTEM_EVENT]: Source: System Resource Monitor. Alert: {event.alert_type}. "
                f"RAM Usage: {event.system_ram_percent:.0f}%. "
                f"Offending Process: {event.process_name} (PID {event.pid}) consuming {event.memory_mb:.0f} MB RAM. "
                "Proactively alert the user with a brief spoken warning and offer to optimize."
            )
            self._dispatch_live_event(prompt)

    def _dispatch_live_event(self, prompt: str) -> None:
        """Dispatches an ambient system event to the registered live session asynchronously."""
        if not self._live_dispatcher:
            return

        dispatcher = self._live_dispatcher
        target_loop = self._live_loop

        def _runner():
            try:
                import inspect
                import asyncio
                res = dispatcher(prompt)
                if inspect.isawaitable(res):
                    try:
                        loop = target_loop or asyncio.get_running_loop()
                        asyncio.run_coroutine_threadsafe(res, loop)
                    except Exception:
                        asyncio.run(res)
            except Exception as exc:
                logger.debug("Live event dispatch notice: %s", exc)

        threading.Thread(target=_runner, daemon=True).start()

    # -----------------------------------------------------------------------
    # Toast Dispatching & Brain Handoff
    # -----------------------------------------------------------------------

    def _show_toast(
        self,
        title: str,
        body: str,
        buttons: List[str],
        callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Displays Windows toast notification in background thread."""
        def _runner():
            # Skip interactive GUI popup in automated test / CI environments
            if os.getenv("MAKIMA_HEADLESS_TEST") == "true":
                logger.debug("Headless test mode: suppressing GUI toast '%s'", title)
                return

            try:
                import win11toast

                def _click(args=None):
                    arg_str = ""
                    if isinstance(args, dict):
                        arg_str = str(args.get("arguments", ""))
                    elif isinstance(args, str):
                        arg_str = args
                    if callback:
                        callback(arg_str)

                win11toast.toast(
                    title,
                    body,
                    buttons=buttons,
                    on_click=_click,
                )
            except Exception as exc:
                logger.debug("Toast alert suppressed or failed: %s", exc)

        threading.Thread(target=_runner, daemon=True).start()

    def _dispatch_brain_task(self, prompt: str) -> None:
        """Dispatches an autonomous background request to Makima's HTTP endpoint."""
        def _call():
            try:
                import httpx
                payload = {
                    "prompt": prompt,
                    "message": prompt,
                    "user_id": "listening_devil",
                    "session_id": "sentinel_auto_fix",
                }
                with httpx.Client(timeout=15.0) as client:
                    client.post(f"{BRAIN_URL}/api/chat", json=payload)
            except Exception as exc:
                logger.debug("Listening Devil brain handoff notice: %s", exc)

        threading.Thread(target=_call, daemon=True).start()


# Alias for backward-compatible naming
ListeningDevilDaemon = SentinelEventDaemon
