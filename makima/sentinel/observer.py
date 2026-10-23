"""
Makima Sentinel — Silent Activity Observer.
Architectural Pattern: APScheduler-driven 60-second snapshot collector.
Captures active process, window title, idle time, fullscreen state, and
clipboard preview — appends as JSON lines to ~/.makima/observations.jsonl.
Auto-rotates file to keep last 10,000 lines (≈7 days at 1 snap/min).
Zero new pip packages — uses only psutil, win32gui, win32process, ctypes (all pre-installed).
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import psutil
import win32con
import win32gui

logger = logging.getLogger("makima.sentinel.observer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_LINES = 10_000
CLIPBOARD_PREVIEW_LEN = 100

# Known gaming / DND process names (lower-case)
GAME_PROCESSES = {
    "javaw.exe",        # Minecraft / Java games
    "gta5.exe",
    "cs2.exe",
    "csgo.exe",
    "steam.exe",
    "epicgameslauncher.exe",
    "valorant.exe",
    "leagueclient.exe",
    "riotclientservices.exe",
    "bf2042.exe",
    "fortnite.exe",
    "roblox.exe",
    "robloxplayerbeta.exe",
    "dota2.exe",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_data_dir() -> Path:
    """Resolve ~/.makima, creating it if absent."""
    from makima.config import get_settings
    raw = get_settings().app.data_dir  # returns "~/.makima" string
    p = Path(raw).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get_idle_seconds() -> float:
    """Returns seconds since last mouse/keyboard input using Win32 LASTINPUTINFO."""
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        tick_count = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        elapsed_ms = (tick_count - lii.dwTime) & 0xFFFFFFFF
        return max(0.0, elapsed_ms / 1000.0)
    return 0.0


def _get_active_window() -> Dict[str, Any]:
    """
    Returns {'process': 'Code.exe', 'title': 'makima_v2 — VS Code', 'hwnd': 12345}.
    Reuses _open_interactive_desktop from makima.tools.os.windows to attach to the
    active Windows desktop station, ensuring 100% reliable foreground window discovery
    even in background worker or subprocess contexts.
    """
    from makima.tools.os.windows import _open_interactive_desktop

    result: Dict[str, Any] = {"process": "", "title": "", "hwnd": 0}
    try:
        with _open_interactive_desktop():
            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd and win32gui.IsWindowVisible(fg_hwnd):
                title = win32gui.GetWindowText(fg_hwnd).strip()
                pid_buf = ctypes.c_ulong(0)
                ctypes.windll.user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(pid_buf))
                pid = pid_buf.value
                proc_name = ""
                if pid:
                    try:
                        proc_name = psutil.Process(pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        proc_name = ""
                if proc_name or title:
                    result["process"] = proc_name
                    result["title"] = title
                    result["hwnd"] = fg_hwnd
                    return result
    except Exception as exc:
        logger.debug("Desktop interactive attach notice: %s", exc)

    # Fallback: scan visible windows via psutil CPU if desktop attach returned 0
    _SKIP_PROCS = {
        "system", "system idle process", "registry", "smss.exe", "csrss.exe",
        "wininit.exe", "services.exe", "lsass.exe", "svchost.exe", "dwm.exe",
        "conhost.exe", "explorer.exe", "taskhostw.exe", "python.exe",
        "pythonw.exe", "cmd.exe", "powershell.exe",
    }
    try:
        best_proc: Optional[psutil.Process] = None
        best_cpu: float = 0.0
        for proc in psutil.process_iter(["pid", "name", "cpu_percent"]):
            try:
                pname = proc.info["name"] or ""
                if pname.lower() in _SKIP_PROCS:
                    continue
                cpu = proc.info["cpu_percent"] or 0.0
                if cpu > best_cpu:
                    best_cpu = cpu
                    best_proc = proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if best_proc:
            result["process"] = best_proc.info["name"]
            result["title"] = ""
    except Exception as exc:
        logger.debug("psutil fallback failed: %s", exc)

    return result


def _is_fullscreen(hwnd: int) -> bool:
    """
    Returns True if the given window handle covers or exceeds the primary monitor.
    Direct O(1) rect comparison without expensive window enumeration.
    """
    if not hwnd:
        return False
    try:
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)  # SM_CYSCREEN
        rect = win32gui.GetWindowRect(hwnd)
        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        return w >= screen_w and h >= screen_h
    except Exception:
        return False


def _get_clipboard_preview(active_process: str = "") -> str:
    """Returns first CLIPBOARD_PREVIEW_LEN chars of clipboard text, masked and stripped of newlines."""
    try:
        from makima.sentinel.event_daemon import BLOCKED_SENSITIVE_PROCESSES, get_sentinel_daemon
        if active_process and active_process.lower() in BLOCKED_SENSITIVE_PROCESSES:
            return "[SENSITIVE_APP_SKIPPED]"
        daemon = get_sentinel_daemon()
        if daemon and daemon._clipboard_watcher and daemon.is_running:
            return daemon._clipboard_watcher._latest_preview
    except Exception:
        pass

    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                if data:
                    preview = " ".join(str(data).split())[:CLIPBOARD_PREVIEW_LEN]
                    from makima.core.guardrails import mask_sensitive_data
                    return mask_sensitive_data(preview)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass
    return ""


def _rotate_observations(path: Path) -> None:
    """Keep only the last MAX_LINES lines in observations.jsonl."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > MAX_LINES:
            path.write_text("".join(lines[-MAX_LINES:]), encoding="utf-8")
    except Exception as exc:
        logger.debug("Rotation skipped: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def take_snapshot() -> Dict[str, Any]:
    """
    Captures a single activity snapshot and appends it to observations.jsonl.
    Called by APScheduler every 60 seconds.
    Non-blocking: offloaded to background thread.
    Returns the snapshot dict for testing/logging.
    """
    return await asyncio.to_thread(_take_snapshot_sync)


def _take_snapshot_sync() -> Dict[str, Any]:
    now = datetime.now()
    window = _get_active_window()
    idle = _get_idle_seconds()
    fullscreen = _is_fullscreen(window.get("hwnd", 0))
    clipboard = _get_clipboard_preview(window.get("process", ""))

    snapshot: Dict[str, Any] = {
        "ts": now.isoformat(timespec="seconds"),
        "weekday": now.strftime("%A"),
        "hour": now.hour,
        "minute": now.minute,
        "active_process": window["process"],
        "active_window_title": window["title"],
        "user_idle_seconds": round(idle, 2),
        "fullscreen": fullscreen,
        "clipboard_preview": clipboard,
    }

    data_dir = _get_data_dir()
    obs_path = data_dir / "observations.jsonl"

    # Ensure file exists
    if not obs_path.exists():
        obs_path.touch()

    # Append snapshot
    try:
        with obs_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
        # Auto-rotate if too large
        _rotate_observations(obs_path)
    except Exception as exc:
        logger.error("Failed to write observation snapshot: %s", exc)

    logger.debug(
        "Snapshot: %s | idle=%.1fs | fullscreen=%s",
        window["process"] or "(none)",
        idle,
        fullscreen,
    )
    return snapshot


def is_dnd_process(process_name: str) -> bool:
    """Returns True if given process name is a known DND/game process."""
    return process_name.lower() in GAME_PROCESSES
