"""
Makima v2 — Hardware & System Telemetry Tools.
Architectural Pattern: Library-first telemetry inspection using psutil directly.
Zero-Cost / Zero-Hardcoding: Dynamically inspects CPU, RAM, Disk, and Battery across platforms.
"""

from __future__ import annotations

import logging
import os
import platform
import time
from typing import Any, Dict, List

import psutil

from makima.tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="get_system_stats",
    description=(
        "Use when you need to check current hardware status — CPU or RAM usage, "
        "available disk space, battery level, or OS details. "
        "Good for diagnosing performance issues, checking free space before large operations, "
        "or answering questions like 'how much RAM is free' or 'is my battery low'."
    ),
    tags=["os", "hardware", "telemetry", "system"],
)
def get_system_stats() -> Dict[str, Any]:
    """
    Get current hardware and OS metrics.

    Returns:
        Dictionary containing:
        - cpu: percent, cores_logical, cores_physical, freq_mhz
        - ram: percent, total_gb, used_gb, available_gb, swap_percent
        - disk: system_drive, percent, total_gb, used_gb, free_gb, partitions
        - battery: has_battery, percent, power_plugged, secsleft
        - os: system, release, version, machine, hostname, uptime_seconds
    """
    # 1. CPU Telemetry
    cpu_pct = psutil.cpu_percent(interval=0.1)
    cpu_cores_logical = psutil.cpu_count(logical=True)
    cpu_cores_physical = psutil.cpu_count(logical=False)
    freq = psutil.cpu_freq()
    cpu_freq_mhz = round(freq.current, 1) if freq else None

    # 2. RAM & Swap Telemetry
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # 3. Disk Storage Telemetry
    system_drive = os.getenv("SystemDrive", "C:")
    if not system_drive.endswith("\\"):
        system_drive += "\\"

    try:
        sys_disk = psutil.disk_usage(system_drive)
        disk_percent = sys_disk.percent
        disk_total_gb = round(sys_disk.total / (1024**3), 2)
        disk_used_gb = round(sys_disk.used / (1024**3), 2)
        disk_free_gb = round(sys_disk.free / (1024**3), 2)
    except Exception:
        disk_percent = 0.0
        disk_total_gb = 0.0
        disk_used_gb = 0.0
        disk_free_gb = 0.0

    partitions_info: List[Dict[str, Any]] = []
    try:
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
                partitions_info.append(
                    {
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "fstype": part.fstype,
                        "total_gb": round(u.total / (1024**3), 2),
                        "used_gb": round(u.used / (1024**3), 2),
                        "free_gb": round(u.free / (1024**3), 2),
                        "percent": u.percent,
                    }
                )
            except (PermissionError, OSError):
                continue
    except Exception as part_exc:
        logger.debug("Failed enumerating disk partitions: %s", part_exc)

    # 4. Battery / Power Telemetry
    battery = psutil.sensors_battery()
    battery_info: Dict[str, Any] = {
        "has_battery": battery is not None,
        "percent": battery.percent if battery else None,
        "power_plugged": battery.power_plugged if battery else True,
        "secsleft": battery.secsleft if battery else None,
    }

    # 5. OS & Host Info
    uptime_seconds = round(time.time() - psutil.boot_time())

    return {
        "cpu": {
            "percent": cpu_pct,
            "cores_logical": cpu_cores_logical,
            "cores_physical": cpu_cores_physical,
            "freq_mhz": cpu_freq_mhz,
        },
        "ram": {
            "percent": mem.percent,
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "swap_percent": swap.percent,
        },
        "disk": {
            "system_drive": system_drive,
            "percent": disk_percent,
            "total_gb": disk_total_gb,
            "used_gb": disk_used_gb,
            "free_gb": disk_free_gb,
            "partitions": partitions_info,
        },
        "battery": battery_info,
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "hostname": platform.node(),
            "uptime_seconds": uptime_seconds,
        },
    }


@tool(
    name="get_gpu_info",
    description="Check dedicated GPU hardware metrics (NVIDIA VRAM, compute usage, temperature, driver version).",
    tags=["os", "hardware", "gpu", "telemetry"],
)
def get_gpu_info() -> Dict[str, Any]:
    """
    Retrieves graphics card (GPU) telemetry using nvidia-smi with cross-platform fallback.

    Returns:
        Dictionary containing GPU model, VRAM total/used/free, temperature, and utilization percent.
    """
    import shutil
    import subprocess

    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {
            "available": False,
            "message": "nvidia-smi is not found. Dedicated NVIDIA GPU or driver not detected.",
            "gpus": [],
        }

    try:
        cmd = [
            nvidia_smi,
            "--query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
        out = subprocess.check_output(cmd, text=True, timeout=3.0).strip()
        gpus: List[Dict[str, Any]] = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                gpus.append({
                    "name": parts[0],
                    "vram_total_mb": float(parts[1]),
                    "vram_used_mb": float(parts[2]),
                    "vram_free_mb": float(parts[3]),
                    "temperature_c": float(parts[4]),
                    "utilization_pct": float(parts[5]),
                })
        return {
            "available": True,
            "count": len(gpus),
            "gpus": gpus,
        }
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
            "gpus": [],
        }


@tool(
    name="find_port_listeners",
    description="Inspect active network listening ports and identify which process/PID is binding them.",
    tags=["os", "network", "ports", "debug"],
)
def find_port_listeners(port: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Inspects TCP/UDP network connections to identify which application is listening on specific ports.

    Args:
        port: Optional specific port number (e.g. 3000, 8000, 5432). If omitted, lists all listening ports.

    Returns:
        List of matching port listeners with port, pid, process_name, and status.
    """
    results: List[Dict[str, Any]] = []
    try:
        connections = psutil.net_connections(kind="inet")
        for conn in connections:
            if conn.status == psutil.CONN_LISTEN:
                laddr = conn.laddr
                if port is not None and laddr.port != port:
                    continue

                proc_name = ""
                if conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        proc_name = proc.name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        proc_name = "[System / Inaccessible]"

                results.append({
                    "port": laddr.port,
                    "ip": laddr.ip,
                    "pid": conn.pid,
                    "process_name": proc_name,
                    "type": "tcp" if conn.type == 1 else "udp",
                })
    except (psutil.AccessDenied, PermissionError):
        logger.debug("Port enumeration requires elevated permissions.")
    except Exception as exc:
        logger.debug("Port inspection notice: %s", exc)

    return sorted(results, key=lambda x: x["port"])

