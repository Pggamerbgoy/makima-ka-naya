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
