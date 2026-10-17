"""
tests/verify_cronjob.py — Step 27 Verification.
Hermes-Style cronjob_manage Tool & APScheduler Integration.

Suites:
  1. Import & Registry Auto-Discovery
  2. Scheduler Lifecycle & Singleton
  3. Job Creation (One-shot DateTrigger, CronTrigger, IntervalTrigger)
  4. List Action Introspection
  5. Pause and Resume Lifecycle
  6. Immediate Run Execution
  7. One-Shot Delayed Firing & Notification Callback Verification
  8. Job Removal
  9. Error Handling & Guardrails
  10. Scheduler Clean Shutdown
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    tag = PASS if ok else FAIL
    msg = f"  {tag} {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append(ok)


# ---------------------------------------------------------------------------
# Suite 1: Import & Registry Auto-Discovery
# ---------------------------------------------------------------------------
def test_import():
    try:
        from makima.tools.automation import (
            cronjob_manage,
            get_scheduler,
            start_scheduler,
            shutdown_scheduler,
            reset_scheduler,
            register_notification_handler,
            unregister_notification_handler,
            get_execution_history,
        )
        record("Import automation module and exports", True)

        from makima.tools.registry import get_registry
        reg = get_registry(auto_discover=True)
        record("Tool registry auto-discovery contains cronjob_manage", "cronjob_manage" in reg)
        return True
    except Exception as e:
        record("Import & Auto-Discovery", False, str(e))
        return False


# ---------------------------------------------------------------------------
# Async Test Runner
# ---------------------------------------------------------------------------
async def run_async_tests():
    from makima.tools.automation import (
        cronjob_manage,
        get_scheduler,
        start_scheduler,
        shutdown_scheduler,
        reset_scheduler,
        register_notification_handler,
        unregister_notification_handler,
        get_execution_history,
        clear_execution_history,
    )
    from makima.core.telemetry import get_telemetry

    # Reset any prior state
    reset_scheduler()

    # Track notifications
    received_notifications = []

    def notification_listener(event):
        received_notifications.append(event)

    register_notification_handler(notification_listener)

    # -----------------------------------------------------------------------
    # Suite 2: Scheduler Lifecycle & Singleton
    # -----------------------------------------------------------------------
    print("\n--- Suite 2: Scheduler Lifecycle ---")
    sched1 = get_scheduler()
    sched2 = get_scheduler()
    record("get_scheduler() returns singleton", sched1 is sched2)

    sched = start_scheduler()
    record("start_scheduler() marks scheduler as running", sched.running is True)

    # -----------------------------------------------------------------------
    # Suite 3: Job Creation
    # -----------------------------------------------------------------------
    print("\n--- Suite 3: Job Creation ---")
    # 1. One-shot delay job (1.0s delay)
    oneshot_res = await cronjob_manage(
        action="create",
        name="oneshot_delay_job",
        prompt="Execute one-shot telemetry pulse",
        delay_seconds=1.0,
    )
    record(
        "Create one-shot delay job (DateTrigger)",
        oneshot_res.get("status") == "created" and "date" in str(oneshot_res.get("trigger")),
        f"trigger: {oneshot_res.get('trigger')}",
    )

    # 2. Cron job (crontab expression)
    cron_res = await cronjob_manage(
        action="create",
        name="recurring_cron_job",
        prompt="Daily backup reminder",
        schedule="0 9 * * *",
    )
    record(
        "Create cron job (CronTrigger from crontab)",
        cron_res.get("status") == "created" and "cron" in str(cron_res.get("trigger")),
        f"trigger: {cron_res.get('trigger')}",
    )

    # 3. Interval job (interval:60)
    interval_res = await cronjob_manage(
        action="create",
        name="recurring_interval_job",
        prompt="Health check ping",
        schedule="interval:60",
    )
    record(
        "Create interval job (IntervalTrigger)",
        interval_res.get("status") == "created" and "interval" in str(interval_res.get("trigger")),
        f"trigger: {interval_res.get('trigger')}",
    )

    # -----------------------------------------------------------------------
    # Suite 4: List Action
    # -----------------------------------------------------------------------
    print("\n--- Suite 4: List Action ---")
    list_res = await cronjob_manage(action="list")
    jobs = list_res.get("jobs", [])
    record("List returns success and >= 3 jobs", list_res.get("status") == "success" and len(jobs) >= 3, f"count: {len(jobs)}")

    job_names = [j["name"] for j in jobs]
    record(
        "All created jobs are present in list output",
        all(n in job_names for n in ["oneshot_delay_job", "recurring_cron_job", "recurring_interval_job"]),
        str(job_names),
    )

    # Verify fields in list output
    interval_info = next((j for j in jobs if j["name"] == "recurring_interval_job"), None)
    has_required_fields = interval_info and all(k in interval_info for k in ("id", "name", "next_run_time", "trigger", "prompt"))
    record("Job info contains id, name, next_run_time, trigger, prompt", bool(has_required_fields))

    # -----------------------------------------------------------------------
    # Suite 5: Pause and Resume
    # -----------------------------------------------------------------------
    print("\n--- Suite 5: Pause and Resume ---")
    pause_res = await cronjob_manage(action="pause", name="recurring_interval_job")
    record("Pause job returns status='paused'", pause_res.get("status") == "paused")

    # Check paused job has next_run_time=None in list
    list_res2 = await cronjob_manage(action="list")
    paused_job = next((j for j in list_res2.get("jobs", []) if j["name"] == "recurring_interval_job"), None)
    record(
        "Paused job has paused=True and next_run_time is None",
        paused_job is not None and paused_job.get("paused") is True and paused_job.get("next_run_time") is None,
    )

    resume_res = await cronjob_manage(action="resume", name="recurring_interval_job")
    record("Resume job returns status='resumed'", resume_res.get("status") == "resumed")

    list_res3 = await cronjob_manage(action="list")
    resumed_job = next((j for j in list_res3.get("jobs", []) if j["name"] == "recurring_interval_job"), None)
    record(
        "Resumed job has paused=False and valid next_run_time",
        resumed_job is not None and resumed_job.get("paused") is False and resumed_job.get("next_run_time") is not None,
    )

    # -----------------------------------------------------------------------
    # Suite 6: Immediate Run Action
    # -----------------------------------------------------------------------
    print("\n--- Suite 6: Immediate Run Action ---")
    run_res = await cronjob_manage(action="run", name="recurring_cron_job")
    record("Run executes callback immediately with status='executed'", run_res.get("status") == "executed")

    # Check that notification listener received the event
    run_event = next((e for e in received_notifications if e.get("name") == "recurring_cron_job"), None)
    record("Notification listener captured immediate run event", run_event is not None)

    # -----------------------------------------------------------------------
    # Suite 7: One-Shot Delayed Firing & Verification
    # -----------------------------------------------------------------------
    print("\n--- Suite 7: One-Shot Delay Firing ---")
    # Initial check: oneshot should not have fired yet
    initial_fired = any(e.get("name") == "oneshot_delay_job" for e in received_notifications)
    record("One-shot delay job has not fired prematurely", not initial_fired)

    # Wait for the delay (1.0s) + grace period (0.4s)
    await asyncio.sleep(1.4)

    # Check notification listener received the oneshot event
    oneshot_fired = any(e.get("name") == "oneshot_delay_job" for e in received_notifications)
    record("One-shot delay job fired after delay and triggered notification", oneshot_fired)

    # Verify execution history
    history = get_execution_history()
    hist_event = next((h for h in history if h.get("name") == "oneshot_delay_job"), None)
    record(
        "Execution history contains oneshot_delay_job record",
        hist_event is not None and hist_event.get("prompt") == "Execute one-shot telemetry pulse",
    )

    # Verify telemetry event was recorded
    tel = get_telemetry()
    recent_tel = tel.get_recent(20)
    cron_tel = [ev for ev in recent_tel if ev.get("event") == "cronjob.execute" and ev.get("name") == "oneshot_delay_job"]
    record("Structured telemetry received 'cronjob.execute' event", len(cron_tel) > 0)

    # -----------------------------------------------------------------------
    # Suite 8: Job Removal
    # -----------------------------------------------------------------------
    print("\n--- Suite 8: Job Removal ---")
    remove_cron = await cronjob_manage(action="remove", name="recurring_cron_job")
    record("Remove recurring_cron_job returns status='removed'", remove_cron.get("status") == "removed")

    remove_interval = await cronjob_manage(action="remove", name="recurring_interval_job")
    record("Remove recurring_interval_job returns status='removed'", remove_interval.get("status") == "removed")

    list_res_after = await cronjob_manage(action="list")
    remaining_names = [j["name"] for j in list_res_after.get("jobs", [])]
    record(
        "Removed jobs no longer present in list",
        "recurring_cron_job" not in remaining_names and "recurring_interval_job" not in remaining_names,
        str(remaining_names),
    )

    # -----------------------------------------------------------------------
    # Suite 9: Error Handling & Edge Cases
    # -----------------------------------------------------------------------
    print("\n--- Suite 9: Error Handling ---")
    bad_action_res = await cronjob_manage(action="invalid_action")
    record("Unknown action returns error dict", bad_action_res.get("status") == "error")

    not_found_pause = await cronjob_manage(action="pause", name="nonexistent_job_12345")
    record("Pause non-existent job returns error dict", not_found_pause.get("status") == "error")

    bad_schedule = await cronjob_manage(action="create", name="bad_cron", schedule="invalid cron schedule string")
    record("Invalid schedule syntax returns error dict", bad_schedule.get("status") == "error")

    # -----------------------------------------------------------------------
    # Suite 10: Scheduler Clean Shutdown
    # -----------------------------------------------------------------------
    print("\n--- Suite 10: Scheduler Clean Shutdown ---")
    shutdown_scheduler(wait=False)
    # Give event loop a microtick to process shutdown
    await asyncio.sleep(0.05)
    record("shutdown_scheduler() shuts down cleanly", sched.running is False)

    # Cleanup listener
    unregister_notification_handler(notification_listener)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Step 27 — Hermes-Style cronjob_manage Verification")
    print("=" * 60)

    if not test_import():
        print("\n[ABORT] Import failed.")
        sys.exit(1)

    asyncio.run(run_async_tests())

    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    print("=" * 60)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
