"""
Makima v2 — Gateway Async Job Scheduler.
Architectural Pattern: AsyncIOScheduler Integration for One-Shot Reminders and Recurring Cron Tasks.
Zero-Hardcoding Guarantee: Fully dynamic ISO datetime parsing, crontab compilation, and async execution.
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger("makima.gateway.scheduler")


class GatewayScheduler:
    """
    Async job and reminder scheduler for Makima Gateway.
    Powered by APScheduler AsyncIOScheduler.
    Supports:
      1. One-shot time-targeted reminders (ISO datetime / relative).
      2. Recurring cron tasks via standard 5-field cron syntax.
      3. Dynamic job cancellation and introspection.
    """

    def __init__(self, timezone_str: str = "UTC"):
        self.timezone_str = timezone_str
        self._scheduler = AsyncIOScheduler(timezone=timezone_str)
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Indicates if the underlying AsyncIOScheduler is active."""
        return self._is_running and bool(self._scheduler.running)

    def start(self) -> None:
        """Starts the async scheduler event loop hooks."""
        if not self._scheduler.running:
            self._scheduler.start()
            self._is_running = True
            logger.info("GatewayScheduler started successfully.")

    def shutdown(self, wait: bool = False) -> None:
        """Shuts down the scheduler and halts pending triggers."""
        if self._scheduler.running:
            self._is_running = False
            self._scheduler.shutdown(wait=wait)
            logger.info("GatewayScheduler shut down cleanly.")

    @staticmethod
    def _parse_datetime(dt_val: Union[str, datetime]) -> datetime:
        """Parses ISO string or ensures datetime is timezone-aware."""
        if isinstance(dt_val, datetime):
            if dt_val.tzinfo is None:
                return dt_val.replace(tzinfo=timezone.utc)
            return dt_val

        # Parse ISO string
        clean_str = dt_val.strip()
        # Handle 'Z' suffix for python < 3.11 compatibility
        if clean_str.endswith("Z"):
            clean_str = clean_str[:-1] + "+00:00"

        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    async def _invoke_callback(callback: Callable[..., Any], *args, **kwargs) -> Any:
        """Safely invokes either an async coroutine or sync function."""
        try:
            if inspect.iscoroutinefunction(callback):
                return await callback(*args, **kwargs)
            res = callback(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res
        except Exception as e:
            logger.error(f"Error executing scheduled job callback: {e}", exc_info=True)

    def schedule_reminder(
        self,
        job_id: str,
        run_at_iso: Union[str, datetime],
        message: str,
        callback: Callable[..., Any],
    ) -> Job:
        """
        Schedules a one-shot reminder at a specific timestamp.

        Args:
            job_id: Unique identifier for the reminder.
            run_at_iso: Target ISO timestamp (e.g. '2026-10-01T12:00:00Z') or datetime.
            message: Content / text of the reminder.
            callback: Async or sync callable invoked when reminder triggers: fn(message) or fn().
        """
        run_dt = self._parse_datetime(run_at_iso)
        trigger = DateTrigger(run_date=run_dt, timezone=self.timezone_str)

        async def _job_wrapper():
            logger.info(f"Triggering reminder [{job_id}]: {message}")
            sig = inspect.signature(callback)
            if len(sig.parameters) > 0:
                await self._invoke_callback(callback, message)
            else:
                await self._invoke_callback(callback)

        job = self._scheduler.add_job(
            _job_wrapper,
            trigger=trigger,
            id=job_id,
            name=f"reminder:{job_id}",
            replace_existing=True,
        )
        logger.info(f"Scheduled one-shot reminder [{job_id}] for {run_dt.isoformat()}")
        return job

    def schedule_cron(
        self,
        job_id: str,
        cron_expr: str,
        callback: Callable[..., Any],
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> Job:
        """
        Schedules a recurring cron task using standard 5-field syntax.

        Args:
            job_id: Unique identifier for the cron task.
            cron_expr: Standard cron expression (e.g. '*/5 * * * *' or '0 9 * * 1-5').
            callback: Async or sync callable to execute on schedule.
            args: Positional arguments to forward to callback.
            kwargs: Keyword arguments to forward to callback.
        """
        trigger = CronTrigger.from_crontab(cron_expr.strip(), timezone=self.timezone_str)
        call_args = args or []
        call_kwargs = kwargs or {}

        async def _cron_wrapper():
            logger.debug(f"Executing scheduled cron task [{job_id}]")
            await self._invoke_callback(callback, *call_args, **call_kwargs)

        job = self._scheduler.add_job(
            _cron_wrapper,
            trigger=trigger,
            id=job_id,
            name=f"cron:{job_id}",
            replace_existing=True,
        )
        logger.info(f"Scheduled recurring cron task [{job_id}] with expression '{cron_expr}'")
        return job

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancels and removes a scheduled job by its identifier.
        Returns True if job was found and removed, False otherwise.
        """
        job = self._scheduler.get_job(job_id)
        if job:
            self._scheduler.remove_job(job_id)
            logger.info(f"Cancelled scheduled job [{job_id}]")
            return True
        return False

    def list_jobs(self) -> List[Dict[str, Any]]:
        """Returns details for all currently scheduled jobs."""
        jobs = self._scheduler.get_jobs()
        job_list = []
        for j in jobs:
            next_run = j.next_run_time.isoformat() if j.next_run_time else None
            job_list.append({
                "id": j.id,
                "name": j.name,
                "next_run_time": next_run,
                "trigger": str(j.trigger),
                "pending": j.next_run_time is not None,
            })
        return job_list
