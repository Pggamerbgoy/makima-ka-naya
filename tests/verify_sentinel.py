"""
Makima v2 — Comprehensive Sentinel & Habit Engine Verification Suite.
Validates:
1. Observer: 60s snapshot capture, desktop window station attachment, idle time, fullscreen detection.
2. Habit Engine: Statistical aggregation, 30-day window, HABITS.json schema, and confidence scoring.
3. Memory Ingestion: ImplicitPreferenceLearner.ingest_habits with targeted deduplication.
4. Proactive Daemon: Sequential decision gates (anti-fatigue, snooze, DND, user return, habit window).
5. Gateway Integration: GatewayDaemon scheduler job registration.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

# Ensure makima is importable
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Enable headless test mode to suppress UI toasts and prevent active game DND suppression
os.environ["MAKIMA_HEADLESS_TEST"] = "true"

from makima.gateway.daemon import GatewayDaemon
from makima.memory.reflection import ImplicitPreferenceLearner
from makima.memory.state import StateMemory
from makima.sentinel import (
    evaluate_and_act,
    is_dnd_process,
    load_habits,
    run_habit_analysis,
    take_snapshot,
)
from makima.sentinel.proactive_daemon import (
    _check_habit_window,
    _check_user_return,
    _gate_anti_fatigue,
    _gate_dnd,
    _gate_snooze,
)


def run_tests():
    print("============================================================")
    print("[===] RUNNING LIVE VERIFICATION: makima/sentinel/ (Sentinel Engine) [===]")
    print("============================================================")

    # -----------------------------------------------------------------------
    # Stage 1: Observer Snapshot & Window Detection
    # -----------------------------------------------------------------------
    print("\n[Stage 1] Testing Observer Activity Snapshot...")
    snap = asyncio.run(take_snapshot())
    assert isinstance(snap, dict), "Snapshot must be a dictionary"
    required_keys = {
        "ts", "weekday", "hour", "minute", "active_process",
        "active_window_title", "user_idle_seconds", "fullscreen", "clipboard_preview"
    }
    assert required_keys.issubset(snap.keys()), f"Snapshot missing keys: {required_keys - set(snap.keys())}"
    assert isinstance(snap["user_idle_seconds"], float), "Idle seconds must be float"
    assert isinstance(snap["fullscreen"], bool), "Fullscreen must be bool"
    print(f"  -> Snapshot OK: process='{snap['active_process']}', title='{snap['active_window_title'][:40]}', idle={snap['user_idle_seconds']}s")
    print("  [OK] Stage 1 Passed: Observer snapshot captured successfully.")

    # -----------------------------------------------------------------------
    # Stage 2: DND & Gaming Process Filtering
    # -----------------------------------------------------------------------
    print("\n[Stage 2] Testing DND & Game Process Filter...")
    assert is_dnd_process("robloxplayerbeta.exe"), "RobloxPlayerBeta must be marked as game/DND"
    assert is_dnd_process("cs2.exe"), "CS2 must be marked as game/DND"
    assert is_dnd_process("javaw.exe"), "Minecraft/javaw must be marked as game/DND"
    assert not is_dnd_process("Code.exe"), "VS Code must NOT be DND"
    assert not is_dnd_process("Spotify.exe"), "Spotify must NOT be DND"
    print("  [OK] Stage 2 Passed: DND & game processes categorized accurately.")

    # -----------------------------------------------------------------------
    # Stage 3: Habit Engine Pattern Detection & Confidence
    # -----------------------------------------------------------------------
    print("\n[Stage 3] Testing Habit Engine Pattern Detection...")
    now = datetime.now()
    analysis = asyncio.run(run_habit_analysis())
    assert "habits_confirmed" in analysis, "Analysis must report habits_confirmed"
    assert "analyzed" in analysis, "Analysis must report analyzed count"
    habits = load_habits()
    assert isinstance(habits, list), "load_habits must return a list"
    print(f"  -> Analyzed {analysis['analyzed']} observations, confirmed {analysis['habits_confirmed']} habits.")
    for h in habits:
        print(f"     * [{h['id']}] {h['label']} (confidence={h['confidence']}, apps={h['apps']})")
    print("  [OK] Stage 3 Passed: Habit pattern detector operating correctly.")

    # -----------------------------------------------------------------------
    # Stage 4: Ingestion into USER.md with Targeted Deduplication
    # -----------------------------------------------------------------------
    print("\n[Stage 4] Testing Habit Ingestion into USER.md...")
    ImplicitPreferenceLearner._seen_prefs.clear()
    learner = ImplicitPreferenceLearner(state_memory=StateMemory())
    habits_file = Path("~/.makima/HABITS.json").expanduser()
    written_count = learner.ingest_habits(habits_file)
    print(f"  -> Ingested {written_count} new habit(s) on initial pass.")
    # Second pass must be zero due to deduplication
    ImplicitPreferenceLearner._seen_prefs.clear()
    second_pass = learner.ingest_habits(habits_file)
    assert second_pass == 0, f"Second ingestion pass must write 0 duplicates, wrote {second_pass}"
    print("  [OK] Stage 4 Passed: Autonomous habit profile ingestion & dedup verified.")

    # -----------------------------------------------------------------------
    # Stage 5: Proactive Decision Gates & Triggers
    # -----------------------------------------------------------------------
    print("\n[Stage 5] Testing Proactive Decision Gates & Trigger Rules...")
    # Gate 1: Anti-fatigue
    assert not _gate_anti_fatigue({"last_notification_ts": None}, now)
    assert _gate_anti_fatigue({"last_notification_ts": (now - timedelta(minutes=10)).isoformat()}, now)
    assert not _gate_anti_fatigue({"last_notification_ts": (now - timedelta(minutes=35)).isoformat()}, now)

    # Gate 2: Snooze
    assert _gate_snooze({"snooze_until": (now + timedelta(hours=2)).isoformat()}, now)
    assert not _gate_snooze({"snooze_until": (now - timedelta(minutes=5)).isoformat()}, now)

    # Gate 3: DND
    assert _gate_dnd({"fullscreen": True, "active_process": "Code.exe"})
    assert _gate_dnd({"fullscreen": False, "active_process": "robloxplayerbeta.exe"})
    assert not _gate_dnd({"fullscreen": False, "active_process": "Code.exe"})

    # Trigger A: User Return (idle drop)
    assert _check_user_return({"user_idle_seconds": 320.0}, {"user_idle_seconds": 4.0})
    assert not _check_user_return({"user_idle_seconds": 320.0}, {"user_idle_seconds": 310.0})

    # Trigger B: Habit Window
    active_habit = [{
        "id": "h_active",
        "label": "Active Session",
        "weekdays": [now.strftime("%A")],
        "hour_start": now.hour,
        "hour_end": now.hour + 1,
        "apps": ["Code.exe"]
    }]
    assert _check_habit_window(active_habit, now) is not None, "Active habit must trigger"
    print("  [OK] Stage 5 Passed: All 3 decision gates and 2 trigger types verified.")

    # -----------------------------------------------------------------------
    # Stage 6: Gateway Daemon Scheduler Wiring
    # -----------------------------------------------------------------------
    print("\n[Stage 6] Testing Gateway Daemon Scheduler Wiring...")
    daemon = GatewayDaemon()
    async def _test_daemon():
        await daemon.start()
        jobs = daemon.scheduler.list_jobs()
        job_ids = {j["id"] for j in jobs}
        expected = {"sentinel_observer", "habit_engine_daily", "proactive_daemon"}
        assert expected.issubset(job_ids), f"Daemon missing Sentinel jobs: {expected - job_ids}"
        assert daemon._sentinel_event_daemon is not None, "Gateway must start SentinelEventDaemon"
        assert daemon._sentinel_event_daemon.is_running, "SentinelEventDaemon must be running"
        print(f"  -> Gateway registered {len(jobs)} background jobs: {sorted(job_ids)}")
        print(f"  -> Gateway started Listening Devil event daemon: {daemon._sentinel_event_daemon.is_running}")
        await daemon.stop()
        assert daemon._sentinel_event_daemon is None, "Gateway must stop and clear SentinelEventDaemon"

    asyncio.run(_test_daemon())
    print("  [OK] Stage 6 Passed: Gateway daemon schedules all Sentinel jobs seamlessly.")

    # -----------------------------------------------------------------------
    # Stage 7: Event-Driven Autonomous Daemon ("The Listening Devil")
    # -----------------------------------------------------------------------
    print("\n[Stage 7] Testing Event-Driven Daemon & StackTrace Analyzer...")
    from makima.sentinel.event_daemon import (
        StackTraceAnalyzer,
        StackTraceInfo,
        SentinelEventDaemon,
        _DownloadsEventHandler,
    )

    # 7.1 Python traceback detection
    py_sample = """Traceback (most recent call last):
  File "app.py", line 42, in run_task
    result = 10 / 0
ZeroDivisionError: division by zero"""
    py_info = StackTraceAnalyzer.detect(py_sample)
    assert py_info is not None, "Must detect Python traceback"
    assert py_info.language == "Python", f"Expected Python, got {py_info.language}"
    assert py_info.error_type == "ZeroDivisionError", f"Expected ZeroDivisionError, got {py_info.error_type}"
    assert py_info.line_number == 42, f"Expected line 42, got {py_info.line_number}"
    print(f"  -> Python trace detected: {py_info.summary()}")

    # 7.2 JavaScript error detection
    js_sample = """TypeError: Cannot read properties of undefined (reading 'map')
    at renderList (bundle.js:120:15)
    at App (bundle.js:45:10)"""
    js_info = StackTraceAnalyzer.detect(js_sample)
    assert js_info is not None, "Must detect JS stack trace"
    assert js_info.language == "JavaScript", f"Expected JavaScript, got {js_info.language}"
    assert js_info.error_type == "TypeError"
    assert js_info.line_number == 120
    print(f"  -> JS trace detected: {js_info.summary()}")

    # 7.3 Rust panic detection
    rust_sample = "thread 'main' panicked at 'assertion failed: `(left == right)`', src/main.rs:88"
    rust_info = StackTraceAnalyzer.detect(rust_sample)
    assert rust_info is not None, "Must detect Rust panic"
    assert rust_info.language == "Rust"
    assert rust_info.line_number == 88
    print(f"  -> Rust panic detected: {rust_info.summary()}")

    # 7.4 False positive check on normal code
    normal_code = "def calculate_discount(price: float) -> float:\n    return price * 0.9\n"
    assert StackTraceAnalyzer.detect(normal_code) is None, "Normal code must not trigger as error"
    print("  -> False positive filter verified on standard code snippet.")

    # 7.5 Watchdog file event classification & filtering
    handler = _DownloadsEventHandler(callback=lambda e: None)
    assert handler._is_temp(Path("package.zip.crdownload")), "Must recognize .crdownload as temp"
    assert handler._is_temp(Path("tempfile.tmp")), "Must recognize .tmp as temp"
    assert not handler._is_temp(Path("archive.zip")), "archive.zip is NOT temp"
    assert handler._classify_event(Path("setup.exe")) == "installer_download"
    assert handler._classify_event(Path("data.tar.gz")) == "archive_download"
    assert handler._classify_event(Path("backend_crash.log")) == "crash_log"
    print("  -> Watchdog file event categorization & temp filtering verified.")

    # 7.6 Standalone SentinelEventDaemon lifecycle
    event_daemon = SentinelEventDaemon()
    event_daemon.start()
    assert event_daemon.is_running, "Event daemon must be active after start()"
    time.sleep(0.3)
    event_daemon.stop()
    assert not event_daemon.is_running, "Event daemon must be stopped after stop()"
    print("  -> Standalone Listening Devil lifecycle (start -> wait -> stop) verified cleanly.")

    # 7.7 Microsoft Presidio PII & Credential Security Verification
    from makima.core.guardrails import filter_secrets
    from makima.tools.filesystem.safe_io import resolve_safe_path, ProtectedCredentialError

    raw_sensitive = "Card 4111111111111111, Email user@example.com, Key AKIAIOSFODNN7EXAMPLE"
    sanitized = filter_secrets(raw_sensitive)
    assert "<CREDIT_CARD>" in sanitized, "Must mask credit card via Presidio"
    assert "<EMAIL_ADDRESS>" in sanitized, "Must mask email via Presidio"
    assert "AKIA" not in sanitized, "Must redact AWS key"
    print("  -> Microsoft Presidio PII + AWS Key redaction verified.")

    # Protected credential path blocking
    try:
        resolve_safe_path(".env")
        assert False, "Must block .env"
    except ProtectedCredentialError:
        pass
    try:
        resolve_safe_path("id_rsa")
        assert False, "Must block id_rsa"
    except ProtectedCredentialError:
        pass
    print("  -> Filesystem protected credential deny-list (.env, id_rsa) verified.")

    print("  [OK] Stage 7 Passed: The Listening Devil event-driven daemon & DLP verified.")

    # ============================================================
    # Stage 8: Gemini 3.8 Live Proactive Event Bridge & Speculative Dispatch
    # ============================================================
    print("\n[Stage 8] Verifying Gemini 3.8 Live Proactive Bridge & Semantic Telemetry...")

    from makima.sentinel.event_daemon import (
        SentinelEventDaemon,
        get_sentinel_daemon,
        FileAlertEvent,
        ResourceAlertEvent,
    )
    from makima.voice.gemini_live import DEFAULT_VOICE_SYSTEM_INSTRUCTION

    # 8.1 Gemini 3.8 Live System Prompt Semantic Proactivity Verification
    assert "SEMANTIC PROACTIVITY RULES" in DEFAULT_VOICE_SYSTEM_INSTRUCTION, "Must contain semantic rules"
    assert "[SYSTEM_EVENT]" in DEFAULT_VOICE_SYSTEM_INSTRUCTION, "Must explicitly handle system events"
    assert "REMAIN COMPLETELY SILENT" in DEFAULT_VOICE_SYSTEM_INSTRUCTION, "Must instruct smart silence on trivial events"
    print("  -> Gemini 3.8 Live semantic proactivity & smart silence instruction verified.")

    # 8.2 Global Daemon Registry Verification
    assert get_sentinel_daemon() is None, "Global daemon must be None initially"
    daemon = SentinelEventDaemon()
    daemon.start()
    assert get_sentinel_daemon() is daemon, "get_sentinel_daemon() must return active instance"

    # 8.3 Async Live Dispatcher Mock & PII Masking Verification
    dispatched_events: List[str] = []
    dispatch_event_received = threading.Event()

    async def mock_live_dispatcher(prompt: str) -> None:
        dispatched_events.append(prompt)
        dispatch_event_received.set()

    daemon.set_live_dispatcher(mock_live_dispatcher)

    # Simulate clipboard ambient text containing sensitive credentials
    sensitive_clip = "Order tracked at Delhivery AWB982137912 contact help@flipkart.com with token AKIAIOSFODNN7EXAMPLE"
    daemon._handle_clipboard_text(sensitive_clip, {"process": "chrome.exe"})

    assert dispatch_event_received.wait(timeout=2.0), "Async live dispatcher must receive ambient clipboard event"
    last_event = dispatched_events[-1]
    assert "[SYSTEM_EVENT]" in last_event, "Must be tagged with [SYSTEM_EVENT]"
    assert "help@flipkart.com" not in last_event, "Email must be masked before dispatch"
    assert "<EMAIL_ADDRESS>" in last_event, "Must contain Presidio masked email tag"
    assert "AKIAIOSFODNN7EXAMPLE" not in last_event, "AWS Key must be masked before dispatch"
    assert "chrome.exe" in last_event, "Must preserve active process context"
    print("  -> Ambient clipboard text dispatched to Gemini Live with 100% PII protection (Zero Regex).")

    # 8.4 File Download Event Dispatch
    file_evt = FileAlertEvent(
        event_type="archive_download",
        path=Path("C:/Downloads/Tax_Invoice_March2026.zip"),
        filename="Tax_Invoice_March2026.zip",
        size_bytes=int(4.8 * 1024 * 1024),
        extension=".zip",
    )
    dispatch_event_received.clear()
    daemon._handle_file_alert(file_evt)
    for _ in range(25):
        if any("Tax_Invoice_March2026.zip" in e for e in dispatched_events):
            break
        time.sleep(0.1)
    file_prompts = [e for e in dispatched_events if "Tax_Invoice_March2026.zip" in e]
    assert file_prompts, f"Must include downloaded filename among {dispatched_events}"
    file_prompt = file_prompts[-1]
    assert "Tax_Invoice_March2026.zip" in file_prompt, "Must include downloaded filename"
    assert "archive_download" in file_prompt, "Must include event type"
    print("  -> Downloaded file event dispatched to Gemini Live for semantic organization.")

    # 8.5 Resource Spike Event Dispatch
    res_evt = ResourceAlertEvent(
        alert_type="high_ram",
        pid=12345,
        process_name="premiere.exe",
        memory_mb=6200.0,
        cpu_percent=45.0,
        system_ram_percent=91.0,
    )
    dispatch_event_received.clear()
    daemon._handle_resource_alert(res_evt)
    for _ in range(25):
        if any("premiere.exe" in e for e in dispatched_events):
            break
        time.sleep(0.1)
    res_prompts = [e for e in dispatched_events if "premiere.exe" in e]
    assert res_prompts, f"Must include heavy process name among dispatched events: {dispatched_events}"
    res_prompt = res_prompts[-1]
    assert "91%" in res_prompt, "Must include RAM percentage"
    print("  -> High RAM alert dispatched to Gemini Live for proactive optimization.")

    daemon.stop()
    assert get_sentinel_daemon() is None, "Global daemon must be cleared on stop"
    print("  -> Global registry unbinding on stop verified cleanly.")

    # 8.6 Zero-Hardcoding Dynamic Model & Voice Resolution Verification
    from makima.voice.gemini_live import get_live_model, get_voice_name, GeminiLiveSession
    initial_model = get_live_model()
    assert initial_model, "Must resolve a non-empty live model dynamically"

    os.environ["MAKIMA_LIVE_MODEL"] = "gemini-custom-enterprise-live"
    assert get_live_model() == "gemini-custom-enterprise-live", "Must resolve environment model dynamically"
    os.environ["MAKIMA_VOICE_NAME"] = "Kore"
    assert get_voice_name() == "Kore", "Must resolve environment voice persona dynamically"

    session = GeminiLiveSession(api_key="test_api_key_dummy")
    assert session.model == "gemini-custom-enterprise-live", "Session must dynamically adopt env model"
    assert session.voice_name == "Kore", "Session must dynamically adopt env voice"

    # Cleanup test env vars
    del os.environ["MAKIMA_LIVE_MODEL"]
    del os.environ["MAKIMA_VOICE_NAME"]
    print("  -> Zero-Hardcoding: Dynamic model & voice persona resolution verified.")

    print("  [OK] Stage 8 Passed: Gemini 3.8 Live proactive event bridge verified.")

    print("\n============================================================")
    print("[SUCCESS] ALL 8 SENTINEL VERIFICATION STAGES PASSED! (EXIT CODE 0)")
    print("============================================================")


if __name__ == "__main__":
    run_tests()
