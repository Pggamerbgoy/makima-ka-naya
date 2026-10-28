"""
Makima v2 — Process Management Tools.
Architectural Pattern: Clean, modular, library-first process inspection and lifecycle control.
Uses 'psutil' directly for fast, cross-platform and Windows process management.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import psutil

from makima.tools.registry import tool

logger = logging.getLogger(__name__)

# Protected process PIDs that should not be terminated by default
PROTECTED_PIDS = {0, 4}


@tool(
    name="list_processes",
    description="Read a list of running operating-system processes with CPU/RAM usage, PID, and status. This is process inventory, not application-window control.",
    tags=["os", "process", "monitoring"],
    purpose="Inspect running processes and identify a target before a process-level action.",
    capabilities=["List process names, PIDs, resource usage, account, status, and start time; sort by CPU, memory, PID, or name."],
    use_when=["The user asks to inspect running processes, find a process consuming resources, or identify a PID."],
    avoid_when=["The user asks to close an application normally; prefer terminate_application.","The user asks for high-level CPU, RAM, battery, or disk summary; prefer get_system_stats.","The user asks to kill a known process; use terminate_process only after identifying the intended target."],
    examples=["Show the top memory-consuming processes.","Find the PID for a named executable."],
    side_effect="Read-only; does not terminate or alter any process.",
)
def list_processes(
    limit: int = 20,
    sort_by: str = "cpu",
) -> List[Dict[str, Any]]:
    """
    List running system processes sorted by resource consumption or identifiers.

    Args:
        limit: Maximum number of processes to return (default: 20). Set to 0 or negative for all.
        sort_by: Metric to sort by: 'cpu', 'memory' (or 'ram'), 'pid', or 'name' (default: 'cpu').

    Returns:
        List of dictionaries containing process metrics:
        pid, name, cpu_percent, memory_percent, memory_mb, status, username, create_time.
    """
    processes: List[Dict[str, Any]] = []

    # Fast iteration over running processes
    for proc in psutil.process_iter(
        ["pid", "name", "cpu_percent", "memory_percent", "memory_info", "status", "create_time", "username"]
    ):
        try:
            info = proc.info
            pid = info.get("pid")
            name = info.get("name") or "unknown"
            cpu_pct = round(info.get("cpu_percent") or 0.0, 1)
            mem_pct = round(info.get("memory_percent") or 0.0, 2)
            status = info.get("status") or "unknown"
            username = info.get("username") or ""
            ctime = info.get("create_time")

            # Fast memory RSS in MB extraction from pre-fetched proc info (avoids per-process syscalls)
            mem_mb: Optional[float] = None
            mem_info = info.get("memory_info")
            if mem_info and hasattr(mem_info, "rss"):
                mem_mb = round(mem_info.rss / (1024 * 1024), 2)

            processes.append(
                {
                    "pid": pid,
                    "name": name,
                    "cpu_percent": cpu_pct,
                    "memory_percent": mem_pct,
                    "memory_mb": mem_mb,
                    "status": status,
                    "username": username,
                    "create_time": ctime,
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # Sorting
    key = sort_by.strip().lower()
    if key in ("memory", "ram", "mem", "memory_percent"):
        processes.sort(key=lambda p: p.get("memory_percent", 0.0) or 0.0, reverse=True)
    elif key == "pid":
        processes.sort(key=lambda p: p.get("pid", 0) or 0)
    elif key == "name":
        processes.sort(key=lambda p: (p.get("name") or "").lower())
    else:
        # Default fallback to CPU
        processes.sort(key=lambda p: p.get("cpu_percent", 0.0) or 0.0, reverse=True)

    if limit and limit > 0:
        return processes[:limit]
    return processes


@tool(
    name="get_process_info",
    description="Retrieve comprehensive details for a specific process by PID or process name.",
    tags=["os", "process", "monitoring"],
)
def get_process_info(
    pid: Optional[int] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get detailed runtime information for a specific process.

    Args:
        pid: The process ID to inspect. If omitted, 'name' must be provided.
        name: Name or substring of process executable to find (e.g. 'chrome.exe' or 'notepad').

    Returns:
        Dictionary with detailed process information or error description.
    """
    if pid is None and not name:
        return {
            "success": False,
            "error": "Either 'pid' or 'name' parameter must be provided.",
        }

    target_proc: Optional[psutil.Process] = None

    if pid is not None:
        try:
            target_proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return {
                "success": False,
                "error": f"No process found with PID {pid}.",
            }
        except psutil.AccessDenied:
            return {
                "success": False,
                "error": f"Access denied reading process with PID {pid}.",
            }
    else:
        # Search by name: first exact case-insensitive match, then substring match
        query = (name or "").strip().lower()
        exact_match: Optional[psutil.Process] = None
        substr_match: Optional[psutil.Process] = None

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if pname == query or pname == f"{query}.exe":
                    exact_match = proc
                    break
                if substr_match is None and query in pname:
                    substr_match = proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        target_proc = exact_match or substr_match
        if target_proc is None:
            return {
                "success": False,
                "error": f"No running process found matching name '{name}'.",
            }

    # Extract process details safely
    try:
        with target_proc.oneshot():
            p_pid = target_proc.pid
            p_name = target_proc.name()
            status = target_proc.status()
            create_time = target_proc.create_time()

            try:
                exe = target_proc.exe()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                exe = None

            try:
                cmdline = target_proc.cmdline()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                cmdline = []

            try:
                username = target_proc.username()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                username = None

            try:
                cpu_pct = target_proc.cpu_percent(interval=None)
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                cpu_pct = 0.0

            try:
                mem_pct = target_proc.memory_percent()
                mem_info = target_proc.memory_info()
                rss_mb = round(mem_info.rss / (1024 * 1024), 2)
                vms_mb = round(mem_info.vms / (1024 * 1024), 2)
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                mem_pct = 0.0
                rss_mb = 0.0
                vms_mb = 0.0

            try:
                num_threads = target_proc.num_threads()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                num_threads = None

            try:
                ppid = target_proc.ppid()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                ppid = None

            try:
                num_handles = target_proc.num_handles() if hasattr(target_proc, "num_handles") else None
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                num_handles = None

        return {
            "success": True,
            "pid": p_pid,
            "name": p_name,
            "exe": exe,
            "cmdline": cmdline,
            "status": status,
            "cpu_percent": round(cpu_pct, 1),
            "memory_percent": round(mem_pct, 2),
            "memory_rss_mb": rss_mb,
            "memory_vms_mb": vms_mb,
            "num_threads": num_threads,
            "num_handles": num_handles,
            "parent_pid": ppid,
            "username": username,
            "create_time": create_time,
        }
    except psutil.NoSuchProcess:
        return {
            "success": False,
            "error": f"Process {target_proc.pid} terminated while reading info.",
        }
    except Exception as exc:
        logger.exception("Error reading process info for PID %s: %s", target_proc.pid, exc)
        return {
            "success": False,
            "error": f"Failed to read process info: {exc}",
        }


@tool(
    name="terminate_process",
    description="Terminate a running process by PID or process name.",
    tags=["os", "process", "control"],
    purpose="Manage a specific operating-system process by its identity.",
    capabilities=[
        "Request graceful termination or forceful termination of a process.",
        "Identify the target by PID or process name.",
    ],
    use_when=[
        "The user explicitly requests ending a process rather than just closing its window.",
        "The target process has been identified and the requested termination mode is appropriate.",
    ],
    avoid_when=[
        "A normal application-close operation is sufficient and should preserve unsaved-work handling.",
        "The request concerns playback state, a browser tab, or an entire operating-system shutdown.",
        "The target is ambiguous or a protected/system process.",
    ],
    examples=[
        "Inspect a process and then request graceful termination by PID.",
    ],
    side_effect="Terminates a process; forceful termination can lose unsaved work or data.",
)
def terminate_process(
    pid: Optional[int] = None,
    name: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Terminate a process gracefully or forcefully by PID or process name.

    Args:
        pid: The process ID to terminate.
        name: The name or substring of the process executable to terminate if pid is not provided.
        force: If True, forces immediate termination (SIGKILL / TerminateProcess).
               If False, requests graceful termination (SIGTERM).

    Returns:
        Dictionary reporting success status, target PID, process name, and termination details.
    """
    if pid is None and not name:
        return {
            "success": False,
            "error": "Either 'pid' or 'name' parameter must be provided.",
        }

    # Locate process
    target_proc: Optional[psutil.Process] = None
    if pid is not None:
        if pid == os.getpid():
            return {
                "success": False,
                "error": f"Cannot terminate the current Makima process (PID {pid}).",
            }
        if pid in PROTECTED_PIDS:
            return {
                "success": False,
                "error": f"Cannot terminate protected system process (PID {pid}).",
            }
        try:
            target_proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return {
                "success": False,
                "error": f"No running process found with PID {pid}.",
            }
    else:
        query = (name or "").strip().lower()
        exact_match: Optional[psutil.Process] = None
        substr_match: Optional[psutil.Process] = None

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.pid == os.getpid() or proc.pid in PROTECTED_PIDS:
                    continue
                pname = (proc.info.get("name") or "").lower()
                if pname == query or pname == f"{query}.exe":
                    exact_match = proc
                    break
                if substr_match is None and query in pname:
                    substr_match = proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        target_proc = exact_match or substr_match
        if target_proc is None:
            return {
                "success": False,
                "error": f"No running process found matching name '{name}'.",
            }

    target_pid = target_proc.pid
    target_name = target_proc.name()

    try:
        # Recursively terminate children first to avoid orphaned subprocess trees
        try:
            children = target_proc.children(recursive=True)
            for child in children:
                try:
                    if force:
                        child.kill()
                    else:
                        child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        if force:
            target_proc.kill()
        else:
            target_proc.terminate()

        # Wait briefly for termination
        try:
            target_proc.wait(timeout=1.5)
            alive = False
        except psutil.TimeoutExpired:
            alive = target_proc.is_running()

        action = "killed (force)" if force else "terminated"
        if not alive:
            return {
                "success": True,
                "pid": target_pid,
                "name": target_name,
                "action": action,
                "message": f"Successfully {action} process '{target_name}' (PID: {target_pid}).",
            }
        else:
            return {
                "success": False,
                "pid": target_pid,
                "name": target_name,
                "action": action,
                "error": f"Process {target_pid} did not exit within timeout.",
            }
    except psutil.NoSuchProcess:
        # Already exited
        return {
            "success": True,
            "pid": target_pid,
            "name": target_name,
            "action": "already_exited",
            "message": f"Process '{target_name}' (PID: {target_pid}) has already exited.",
        }
    except psutil.AccessDenied:
        return {
            "success": False,
            "pid": target_pid,
            "name": target_name,
            "error": f"Access denied terminating process '{target_name}' (PID: {target_pid}). Administrator privileges may be required.",
        }
    except Exception as exc:
        logger.exception("Error terminating process %s: %s", target_pid, exc)
        return {
            "success": False,
            "pid": target_pid,
            "name": target_name,
            "error": f"Failed to terminate process: {exc}",
        }
