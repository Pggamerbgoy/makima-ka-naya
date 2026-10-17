"""
Makima v2 — Automation & Cron Jobs Package (Step 27).
Architectural Pattern: Library-First APScheduler AsyncIOScheduler with Hermes-style tool management.
Zero-Hardcoding Guarantee: Dynamic crontab, interval triggers, and structured telemetry emission.
"""

from __future__ import annotations

from makima.tools.automation.cronjob import (
    cronjob_manage,
    get_scheduler,
    start_scheduler,
    shutdown_scheduler,
    reset_scheduler,
    register_notification_handler,
    unregister_notification_handler,
    clear_notification_handlers,
    get_execution_history,
    clear_execution_history,
)

__all__ = [
    "cronjob_manage",
    "get_scheduler",
    "start_scheduler",
    "shutdown_scheduler",
    "reset_scheduler",
    "register_notification_handler",
    "unregister_notification_handler",
    "clear_notification_handlers",
    "get_execution_history",
    "clear_execution_history",
]
