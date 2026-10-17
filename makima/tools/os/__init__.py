"""
Makima v2 — Operating System & Desktop Management Tools.
Exports tools for process lifecycle, window discovery/manipulation, application launching, and telemetry.
"""

from makima.tools.os.app_opener import (
    get_installed_applications,
    launch_application,
    terminate_application,
)
from makima.tools.os.apps import launch_app
from makima.tools.os.notifications import show_desktop_notification
from makima.tools.os.processes import (
    get_process_info,
    list_processes,
    terminate_process,
)
from makima.tools.os.system_info import get_system_stats
from makima.tools.os.windows import (
    focus_window,
    list_open_windows,
    maximize_window,
    minimize_window,
)

__all__ = [
    # Process tools
    "list_processes",
    "get_process_info",
    "terminate_process",
    # Window tools
    "list_open_windows",
    "focus_window",
    "minimize_window",
    "maximize_window",
    # Application tools
    "launch_app",
    "launch_application",
    "terminate_application",
    "get_installed_applications",
    # Notification tools
    "show_desktop_notification",
    # System Telemetry tools
    "get_system_stats",
]

