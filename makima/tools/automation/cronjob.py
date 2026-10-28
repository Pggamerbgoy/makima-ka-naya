"""
Makima v2 — Hermes-Style Cron & Automation Tool (Step 27).
Architectural Pattern: AsyncIOScheduler Integration with Native Triggers.
Zero-Hardcoding Guarantee: Fully dynamic crontab parsing, interval conversion, and async execution.
No custom polling loops, zero file locks — 100% library-first with APScheduler.
"""

from __future__ import annotations

import inspect
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from makima.core.telemetry import get_telemetry
from makima.tools.registry import tool

logger = logging.getLogger("makima.tools.automation.cronjob")

# ---------------------------------------------------------------------------
# Scheduler Singleton & Lifecycle
# ---------------------------------------------------------------------------

_SCHEDULER: Optional[AsyncIOScheduler] = None
_JOB_METADATA: Dict[str, Dict[str, Any]] = {}
_NOTIFICATION_HANDLERS: List[Callable[[Dict[str, Any]], Any]] = []
_EXECUTION_HISTORY: List[Dict[str, Any]] = []


def get_scheduler() -> AsyncIOScheduler:
    """
    Returns the global AsyncIOScheduler singleton instance.
    Uses UTC timezone by default.
    """
    global _SCHEDULER
    if _SCHEDULER is None:
        _SCHEDULER = AsyncIOScheduler(timezone=timezone.utc)
    return _SCHEDULER


def start_scheduler() -> AsyncIOScheduler:
    """
    Starts the global AsyncIOScheduler if it is not already running.
    Returns the running AsyncIOScheduler instance.
    """
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("Automation AsyncIOScheduler started successfully.")
    return scheduler


def shutdown_scheduler(wait: bool = False) -> None:
    """
    Shuts down the global AsyncIOScheduler and cleans up instance reference.
    """
    global _SCHEDULER
    if _SCHEDULER is not None:
        if _SCHEDULER.running:
            _SCHEDULER.shutdown(wait=wait)
            logger.info("Automation AsyncIOScheduler shut down.")
        _SCHEDULER = None


def reset_scheduler() -> None:
    """Resets the scheduler, metadata, and handlers (useful for test isolation)."""
    shutdown_scheduler(wait=False)
    _JOB_METADATA.clear()
    _NOTIFICATION_HANDLERS.clear()
    _EXECUTION_HISTORY.clear()


# ---------------------------------------------------------------------------
# Notification & Execution Hooks
# ---------------------------------------------------------------------------

def register_notification_handler(handler: Callable[[Dict[str, Any]], Any]) -> None:
    """Registers a callback or listener to receive cronjob execution notifications."""
    if handler not in _NOTIFICATION_HANDLERS:
        _NOTIFICATION_HANDLERS.append(handler)


def unregister_notification_handler(handler: Callable[[Dict[str, Any]], Any]) -> None:
    """Unregisters a previously registered notification handler."""
    if handler in _NOTIFICATION_HANDLERS:
        _NOTIFICATION_HANDLERS.remove(handler)


def clear_notification_handlers() -> None:
    """Clears all registered notification handlers."""
    _NOTIFICATION_HANDLERS.clear()


def get_execution_history() -> List[Dict[str, Any]]:
    """Returns a copy of the execution history of scheduled jobs."""
    return list(_EXECUTION_HISTORY)


def clear_execution_history() -> None:
    """Clears the execution history."""
    _EXECUTION_HISTORY.clear()


async def _cron_job_executor(job_id: str, name: str, prompt: str) -> Dict[str, Any]:
    """
    Standard execution callback triggered by APScheduler when a job fires.
    Logs execution, emits telemetry event, and notifies registered handlers.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    now_ts = time.time()
    logger.info("Cronjob fired: [%s] '%s' | Prompt: %s", job_id, name, prompt)

    # 1. Update job metadata
    if job_id in _JOB_METADATA:
        _JOB_METADATA[job_id]["last_run"] = now_iso
        _JOB_METADATA[job_id]["run_count"] = _JOB_METADATA[job_id].get("run_count", 0) + 1

    payload: Dict[str, Any] = {
        "job_id": job_id,
        "name": name,
        "prompt": prompt,
        "status": "fired",
        "timestamp": now_ts,
        "fired_at": now_iso,
    }

    # 2. Emit telemetry event
    try:
        tel = get_telemetry()
        await tel.emit("cronjob.execute", {
            "job_id": job_id,
            "name": name,
            "prompt": prompt,
            "fired_at": now_iso,
        })
    except Exception as exc:
        logger.warning("Telemetry emit failed for cronjob [%s]: %s", job_id, exc)

    # 3. Dispatches to registered notification handlers
    handler_results = []
    for handler in list(_NOTIFICATION_HANDLERS):
        try:
            if inspect.iscoroutinefunction(handler):
                res = await handler(payload)
            else:
                res = handler(payload)
                if inspect.isawaitable(res):
                    res = await res
            handler_results.append(res)
        except Exception as exc:
            logger.error("Error in cronjob notification handler: %s", exc, exc_info=True)

    _EXECUTION_HISTORY.append(payload)
    if len(_EXECUTION_HISTORY) > 500:
        del _EXECUTION_HISTORY[: len(_EXECUTION_HISTORY) - 500]

    return {
        "job_id": job_id,
        "name": name,
        "prompt": prompt,
        "status": "fired",
        "fired_at": now_iso,
        "handlers_notified": len(handler_results),
    }


# ---------------------------------------------------------------------------
# Trigger Parsing & Resolution
# ---------------------------------------------------------------------------

CRON_PRESETS: Dict[str, str] = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


def _parse_interval_trigger(val: str) -> IntervalTrigger:
    """Parses interval strings such as 'interval:60', 'interval:10m', 'interval:2h'."""
    raw = val.strip().lower()
    if raw.startswith("interval:"):
        raw = raw[len("interval:"):].strip()
    elif raw.startswith("interval="):
        raw = raw[len("interval="):].strip()
    elif raw.startswith("every "):
        raw = raw[len("every "):].strip()

    m = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]*)$", raw)
    if not m:
        raise ValueError(
            f"Invalid interval format: '{val}'. Expected format e.g. 'interval:60', 'interval:10m', 'interval:1h'"
        )

    amount = float(m.group(1))
    unit = m.group(2).lower()

    if unit in ("", "s", "sec", "secs", "second", "seconds"):
        return IntervalTrigger(seconds=amount, timezone=timezone.utc)
    elif unit in ("m", "min", "mins", "minute", "minutes"):
        return IntervalTrigger(minutes=amount, timezone=timezone.utc)
    elif unit in ("h", "hr", "hrs", "hour", "hours"):
        return IntervalTrigger(hours=amount, timezone=timezone.utc)
    elif unit in ("d", "day", "days"):
        return IntervalTrigger(days=amount, timezone=timezone.utc)
    elif unit in ("w", "wk", "wks", "week", "weeks"):
        return IntervalTrigger(weeks=amount, timezone=timezone.utc)
    else:
        raise ValueError(f"Unknown interval unit '{unit}' in '{val}'. Supported units: s, m, h, d, w")


def _build_trigger(
    schedule: str = "",
    delay_seconds: Optional[float] = None,
) -> Union[DateTrigger, CronTrigger, IntervalTrigger]:
    """Resolves DateTrigger, CronTrigger, or IntervalTrigger based on parameters."""
    # 1. Delay seconds -> DateTrigger (now + delay_seconds)
    if delay_seconds is not None:
        if delay_seconds < 0:
            raise ValueError(f"delay_seconds must be non-negative, got {delay_seconds}")
        run_at = datetime.now(timezone.utc) + timedelta(seconds=float(delay_seconds))
        return DateTrigger(run_date=run_at, timezone=timezone.utc)

    # 2. Schedule string
    clean_sched = schedule.strip()
    if not clean_sched:
        raise ValueError("Either 'schedule' or 'delay_seconds' must be provided.")

    # Check interval
    lowered = clean_sched.lower()
    if lowered.startswith("interval:") or lowered.startswith("interval=") or lowered.startswith("every "):
        return _parse_interval_trigger(clean_sched)

    # Check cron preset
    if clean_sched in CRON_PRESETS:
        clean_sched = CRON_PRESETS[clean_sched]

    # Check 5-field cron
    parts = clean_sched.split()
    if len(parts) == 5:
        try:
            return CronTrigger.from_crontab(clean_sched, timezone=timezone.utc)
        except Exception as exc:
            raise ValueError(f"Failed to parse cron expression '{clean_sched}': {exc}") from exc

    # Fallback: try parsing as interval if e.g. '60s' or '10m'
    try:
        return _parse_interval_trigger(clean_sched)
    except Exception:
        pass

    raise ValueError(
        f"Unrecognized schedule expression: '{schedule}'. "
        f"Provide a 5-field cron format (e.g. '0 9 * * *'), an interval (e.g. 'interval:60'), or delay_seconds."
    )


def _find_job(scheduler: AsyncIOScheduler, target: str) -> Optional[Job]:
    """Finds an active job by ID or name (with case-insensitive fallback)."""
    if not target:
        return None

    # 1. Exact ID match
    job = scheduler.get_job(target)
    if job is not None:
        return job

    # 2. Single-pass Name or Case-insensitive match
    target_lower = target.lower()
    fallback_job = None
    for j in scheduler.get_jobs():
        if j.name == target:
            return j
        if fallback_job is None and (j.id.lower() == target_lower or (j.name and j.name.lower() == target_lower)):
            fallback_job = j

    return fallback_job


# ---------------------------------------------------------------------------
# Tool Implementation: cronjob_manage
# ---------------------------------------------------------------------------

@tool(
    name="cronjob_manage",
    description=(
        "Manage Makima's scheduled reminders and recurring jobs. Supports a one-shot delay (delay_seconds), "
        "5-field cron expression (for example schedule='0 9 * * *'), and intervals such as schedule='interval:60'. "
        "Actions: create, list, pause, resume, remove, run. Use only for explicit scheduling or managing an existing job; "
        "do not use it to perform an immediate task."
    ),
    tags=["automation", "cron", "scheduler", "jobs"],
    purpose="Create, inspect, pause, resume, manually run, or remove scheduled reminders and recurring jobs.",
    capabilities=[
        "Create one-shot delayed jobs or recurring cron/interval jobs.",
        "List existing jobs and their next run time.",
        "Pause, resume, manually run, or remove a named job.",
    ],
    use_when=[
        "The user explicitly asks to remind them later, schedule a future action, or repeat a task periodically.",
        "The user asks to list, pause, resume, manually run, or remove an already scheduled job.",
    ],
    avoid_when=[
        "The user asks for an immediate action rather than a scheduled one.",
        "The user asks a question about time/date without requesting a reminder or recurring job.",
        "The user asks to execute an automated workflow; confirm that a scheduled handler supports it instead of assuming the prompt field itself runs arbitrary workflows.",
    ],
    examples=[
        "Remind me in 30 minutes to check the download.",
        "Schedule a recurring status check every hour.",
        "List and remove an existing reminder by name.",
    ],
    side_effect="Creates or changes scheduler jobs; jobs can continue firing until paused or removed.",
)
async def cronjob_manage(
    action: str,
    name: str = "",
    prompt: str = "",
    schedule: str = "",
    delay_seconds: Optional[float] = None,
    enabled: bool = True,
) -> Dict[str, Any]:
    """
    Manages scheduled cron jobs, reminders, and periodic background tasks.

    Args:
        action: The operation to perform ('create', 'list', 'pause', 'resume', 'remove', 'run').
        name: Name or identifier of the job.
        prompt: Task prompt or notification message executed when the job fires.
        schedule: Cron expression (e.g. '0 9 * * *') or interval string (e.g. 'interval:60').
        delay_seconds: Delay in seconds from now for one-shot execution (uses DateTrigger).
        enabled: Whether the job is initially enabled (default: True).

    Returns:
        Dict with status and details of the operation.
    """
    act = action.strip().lower()
    scheduler = start_scheduler()

    # 1. CREATE
    if act == "create":
        job_name = name.strip() or f"job_{uuid.uuid4().hex[:8]}"
        job_id = job_name

        try:
            trigger = _build_trigger(schedule=schedule, delay_seconds=delay_seconds)
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        job = scheduler.add_job(
            _cron_job_executor,
            trigger=trigger,
            args=[job_id, job_name, prompt],
            id=job_id,
            name=job_name,
            replace_existing=True,
        )

        if not enabled:
            job.pause()

        _JOB_METADATA[job_id] = {
            "id": job_id,
            "name": job_name,
            "prompt": prompt,
            "schedule": schedule,
            "delay_seconds": delay_seconds,
            "trigger": str(job.trigger),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "enabled": enabled,
            "last_run": None,
            "run_count": 0,
        }

        return {
            "status": "created",
            "job_id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
            "prompt": prompt,
            "enabled": enabled,
        }

    # 2. LIST
    elif act == "list":
        jobs_list: List[Dict[str, Any]] = []
        for j in scheduler.get_jobs():
            meta = _JOB_METADATA.get(j.id, {})
            job_prompt = meta.get("prompt", "")
            if not job_prompt and len(j.args) > 2:
                job_prompt = str(j.args[2])

            jobs_list.append({
                "id": j.id,
                "name": j.name,
                "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
                "trigger": str(j.trigger),
                "prompt": job_prompt,
                "paused": j.next_run_time is None,
                "enabled": meta.get("enabled", j.next_run_time is not None),
            })

        return {
            "status": "success",
            "count": len(jobs_list),
            "jobs": jobs_list,
        }

    # 3. PAUSE
    elif act == "pause":
        target = name.strip()
        if not target:
            return {"status": "error", "error": "Action 'pause' requires 'name' (or job ID)."}

        job = _find_job(scheduler, target)
        if job is None:
            return {"status": "error", "error": f"Job '{target}' not found."}

        job.pause()
        if job.id in _JOB_METADATA:
            _JOB_METADATA[job.id]["enabled"] = False

        return {
            "status": "paused",
            "job_id": job.id,
            "name": job.name,
        }

    # 4. RESUME
    elif act == "resume":
        target = name.strip()
        if not target:
            return {"status": "error", "error": "Action 'resume' requires 'name' (or job ID)."}

        job = _find_job(scheduler, target)
        if job is None:
            return {"status": "error", "error": f"Job '{target}' not found."}

        job.resume()
        if job.id in _JOB_METADATA:
            _JOB_METADATA[job.id]["enabled"] = True

        return {
            "status": "resumed",
            "job_id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        }

    # 5. REMOVE
    elif act == "remove":
        target = name.strip()
        if not target:
            return {"status": "error", "error": "Action 'remove' requires 'name' (or job ID)."}

        job = _find_job(scheduler, target)
        if job is None:
            return {"status": "error", "error": f"Job '{target}' not found."}

        job_id = job.id
        job_name = job.name
        job.remove()
        _JOB_METADATA.pop(job_id, None)

        return {
            "status": "removed",
            "job_id": job_id,
            "name": job_name,
        }

    # 6. RUN
    elif act == "run":
        target = name.strip()
        if not target:
            return {"status": "error", "error": "Action 'run' requires 'name' (or job ID)."}

        job = _find_job(scheduler, target)
        if job is None:
            return {"status": "error", "error": f"Job '{target}' not found."}

        func = job.func
        args = job.args or ()
        kwargs = job.kwargs or {}

        try:
            if inspect.iscoroutinefunction(func):
                res = await func(*args, **kwargs)
            else:
                res = func(*args, **kwargs)
                if inspect.isawaitable(res):
                    res = await res
        except Exception as exc:
            logger.error("Error executing job '%s' immediately: %s", target, exc, exc_info=True)
            return {"status": "error", "error": f"Execution error: {exc}"}

        return {
            "status": "executed",
            "job_id": job.id,
            "name": job.name,
            "result": res,
        }

    # UNKNOWN ACTION
    else:
        return {
            "status": "error",
            "error": f"Unknown action '{action}'. Supported actions: create, list, pause, resume, remove, run.",
        }
