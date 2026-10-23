"""
Live verification script for Phase 4 Step 12: Gateway Daemon Core, Security & Scheduler.
Tests:
  1. GatewaySecurityManager: Allowlist verification, rejection, and wildcard bypass.
  2. GatewaySecurityManager: Ephemeral pairing code generation, single-use verification, and persistent storage reload.
  3. GatewayScheduler: AsyncIOScheduler lifecycle, one-shot reminder trigger, recurring cron registration, and cancellation.
  4. GatewayDaemon: Master supervisor lifecycle with mock adapter start/stop orchestration and clean termination.
"""

import asyncio
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure makima is importable
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.gateway import (
    GatewayDaemon,
    GatewayScheduler,
    GatewaySecurityManager,
)


def test_security_allowlist_and_rejection():
    print("[TEST 1] Testing GatewaySecurityManager allowlist authorization & rejection...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = Path(tmp_dir) / "auth.json"

        # 1. Configured allowlist only
        sec = GatewaySecurityManager(
            allow_all_users=False,
            allowlist_user_ids=["user_admin", "123456789"],
            pairing_code_enabled=False,
            storage_path=storage_file,
        )

        assert sec.is_user_authorized("telegram", "user_admin") is True
        assert sec.is_user_authorized("discord", "123456789") is True
        assert sec.is_user_authorized("telegram", "unknown_hacker") is False
        assert sec.is_user_authorized("discord", "999999999") is False

        # 2. Allow all users override
        sec_open = GatewaySecurityManager(
            allow_all_users=True,
            allowlist_user_ids=[],
            storage_path=storage_file,
        )
        assert sec_open.is_user_authorized("telegram", "anyone") is True

        # 3. Wildcard allowlist
        sec_wildcard = GatewaySecurityManager(
            allow_all_users=False,
            allowlist_user_ids=["*"],
            storage_path=storage_file,
        )
        assert sec_wildcard.is_user_authorized("whatsapp", "+1234567890") is True

    print("  -> PASSED: Static allowlist, rejection of unauthorized users, and open overrides verified!")


def test_security_pairing_system_and_persistence():
    print("[TEST 2] Testing ephemeral pairing code generation, verification, and persistence...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = Path(tmp_dir) / "paired_users.json"

        sec = GatewaySecurityManager(
            allow_all_users=False,
            allowlist_user_ids=[],
            pairing_code_enabled=True,
            storage_path=storage_file,
            ttl_seconds=60,
        )

        # Before pairing, user is rejected
        assert sec.is_user_authorized("telegram", "alice_tg") is False

        # Generate pairing code
        code = sec.generate_pairing_code()
        assert code.startswith("MK-"), f"Pairing code should begin with 'MK-', got {code}"
        assert len(code) == 7, f"Expected 7 characters (MK-XXXX), got {len(code)}"
        assert sec.get_active_pairing_code() == code

        # Bad code rejection
        bad_res = sec.verify_pairing_code("telegram", "alice_tg", "MK-WRONG")
        assert bad_res is False
        assert sec.is_user_authorized("telegram", "alice_tg") is False

        # Correct code pairing
        ok = sec.verify_pairing_code("telegram", "alice_tg", code)
        assert ok is True
        assert sec.is_user_authorized("telegram", "alice_tg") is True

        # Single-use guarantee: second attempt with same code must fail
        assert sec.get_active_pairing_code() is None
        second_attempt = sec.verify_pairing_code("discord", "bob_dc", code)
        assert second_attempt is False

        # Test persistence across new manager instance pointing to same file
        sec_reloaded = GatewaySecurityManager(
            allow_all_users=False,
            allowlist_user_ids=[],
            storage_path=storage_file,
        )
        assert sec_reloaded.is_user_authorized("telegram", "alice_tg") is True

        # Test revocation
        revoked = sec_reloaded.revoke_user("telegram", "alice_tg")
        assert revoked is True
        assert sec_reloaded.is_user_authorized("telegram", "alice_tg") is False

        # Expired code check
        sec_expired = GatewaySecurityManager(
            allow_all_users=False,
            allowlist_user_ids=[],
            storage_path=storage_file,
            ttl_seconds=-1,  # Already expired
        )
        exp_code = sec_expired.generate_pairing_code()
        assert sec_expired.verify_pairing_code("telegram", "charlie", exp_code) is False

    print("  -> PASSED: Pairing code single-use lifecycle, rejection, and disk persistence verified!")


async def test_gateway_scheduler_reminders_and_cron():
    print("[TEST 3] Testing GatewayScheduler (AsyncIOScheduler reminders and recurring cron)...")

    scheduler = GatewayScheduler(timezone_str="UTC")
    scheduler.start()
    assert scheduler.is_running is True

    try:
        reminder_fired = asyncio.Event()
        received_messages = []

        async def reminder_callback(msg: str):
            received_messages.append(msg)
            reminder_fired.set()

        # Schedule reminder for 0.4s into future
        target_time = datetime.now(timezone.utc) + timedelta(seconds=0.4)
        target_iso = target_time.isoformat()

        job = scheduler.schedule_reminder(
            job_id="test_rem_001",
            run_at_iso=target_iso,
            message="Meeting with engineering lead",
            callback=reminder_callback,
        )
        assert job is not None
        assert job.id == "test_rem_001"

        # Wait for trigger
        await asyncio.wait_for(reminder_fired.wait(), timeout=2.0)
        assert len(received_messages) == 1
        assert received_messages[0] == "Meeting with engineering lead"

        # Test Cron Registration
        cron_called = []

        def dummy_cron():
            cron_called.append(True)

        cron_job = scheduler.schedule_cron(
            job_id="test_cron_hourly",
            cron_expr="0 * * * *",
            callback=dummy_cron,
        )
        assert cron_job.id == "test_cron_hourly"

        # List jobs
        jobs = scheduler.list_jobs()
        job_ids = [j["id"] for j in jobs]
        assert "test_cron_hourly" in job_ids

        # Cancel job
        cancelled = scheduler.cancel_job("test_cron_hourly")
        assert cancelled is True
        assert "test_cron_hourly" not in [j["id"] for j in scheduler.list_jobs()]

    finally:
        scheduler.shutdown(wait=False)
        assert scheduler.is_running is False

    print("  -> PASSED: GatewayScheduler one-shot reminder, cron job, and cancellation verified!")


async def test_gateway_daemon_lifecycle():
    print("[TEST 4] Testing GatewayDaemon master lifecycle supervisor...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = Path(tmp_dir) / "daemon_auth.json"

        sec = GatewaySecurityManager(
            allow_all_users=False,
            allowlist_user_ids=["admin"],
            storage_path=storage_file,
        )
        sched = GatewayScheduler()

        daemon = GatewayDaemon(security_manager=sec, scheduler=sched)

        # Create mock adapter
        class MockPlatformAdapter:
            def __init__(self, name: str):
                self.name = name
                self.started = False
                self.stopped = False

            async def start(self):
                self.started = True

            async def stop(self):
                self.stopped = True

        tg_adapter = MockPlatformAdapter("telegram")
        dc_adapter = MockPlatformAdapter("discord")

        daemon.register_adapter("telegram", tg_adapter)
        daemon.register_adapter("discord", dc_adapter)

        assert len(daemon.adapters) == 2
        assert daemon.get_adapter("telegram") is tg_adapter

        # Start daemon
        await daemon.start()
        assert daemon.is_running is True
        assert daemon.scheduler.is_running is True
        assert tg_adapter.started is True
        assert dc_adapter.started is True

        # Stop daemon
        await daemon.stop()
        assert daemon.is_running is False
        assert daemon.scheduler.is_running is False
        assert tg_adapter.stopped is True
        assert dc_adapter.stopped is True

    print("  -> PASSED: GatewayDaemon multi-adapter supervisor startup and clean shutdown verified!")


async def main():
    print("=" * 60)
    print("RUNNING LIVE VERIFICATION: makima/gateway/ (Core, Security, Scheduler)")
    print("=" * 60)

    test_security_allowlist_and_rejection()
    test_security_pairing_system_and_persistence()
    await test_gateway_scheduler_reminders_and_cron()
    await test_gateway_daemon_lifecycle()

    print("=" * 60)
    print("ALL GATEWAY CORE VERIFICATION CHECKS PASSED! (EXIT CODE 0)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
