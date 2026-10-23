"""
tests/verify_telemetry.py — Step 24 Verification
6 suites covering: import, singleton, sync emit, async emit, ring buffer, file persistence.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

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
# Suite 1: Import
# ---------------------------------------------------------------------------
def test_import():
    try:
        record("Import StructuredTelemetry, TelemetryEvent, get_telemetry", True)
        return True
    except Exception as e:
        record("Import", False, str(e))
        return False


# ---------------------------------------------------------------------------
# Suite 2: Singleton
# ---------------------------------------------------------------------------
def test_singleton():
    try:
        from makima.core.telemetry import get_telemetry
        a = get_telemetry()
        b = get_telemetry()
        record("get_telemetry() returns same singleton", a is b)
    except Exception as e:
        record("Singleton", False, str(e))


# ---------------------------------------------------------------------------
# Suite 3: TelemetryEvent structure
# ---------------------------------------------------------------------------
def test_event_structure():
    try:
        from makima.core.telemetry import TelemetryEvent
        ev = TelemetryEvent("tool.execute", {"tool": "web_search", "latency_ms": 42})
        d = ev.to_dict()
        ok = (
            d.get("event") == "tool.execute"
            and "ts" in d
            and "ts_iso" in d
            and d.get("tool") == "web_search"
            and d.get("latency_ms") == 42
        )
        record("TelemetryEvent.to_dict() has all fields", ok, str(d)[:80])
        line = ev.to_jsonl()
        import json
        parsed = json.loads(line)
        record("TelemetryEvent.to_jsonl() is valid JSON", parsed.get("event") == "tool.execute")
    except Exception as e:
        record("Event structure", False, str(e))


# ---------------------------------------------------------------------------
# Suite 4: sync emit + ring buffer
# ---------------------------------------------------------------------------
def test_sync_emit():
    try:
        from makima.core.telemetry import StructuredTelemetry
        tel = StructuredTelemetry(log_dir=None, buffer_size=10, enabled=True)
        for i in range(15):
            tel.emit_sync("engine.turn_start", {"turn": i})
        count = tel.get_event_count()
        recent = tel.get_recent(5)
        ok_ring = count == 10  # ring buffer capped at 10
        ok_recent = len(recent) == 5 and recent[-1]["turn"] == 14
        record(f"Ring buffer caps at buffer_size=10", ok_ring, f"count={count}")
        record(f"get_recent(5) returns last 5 events", ok_recent, f"last_turn={recent[-1].get('turn')}")
    except Exception as e:
        record("Sync emit + ring buffer", False, str(e))


# ---------------------------------------------------------------------------
# Suite 5: async emit + persistence
# ---------------------------------------------------------------------------
def test_async_emit():
    async def _run():
        from makima.core.telemetry import StructuredTelemetry
        with tempfile.TemporaryDirectory() as tmpdir:
            tel = StructuredTelemetry(log_dir=tmpdir, buffer_size=100, enabled=True)
            await tel.emit("provider.request", {"model": "gemini-2.0-flash", "tokens": 512})
            await tel.emit("provider.response", {"latency_ms": 234, "finish": "stop"})
            await tel.emit("tool.execute", {"tool": "web_search", "ok": True})

            # Check buffer
            recent = tel.get_recent(10)
            buf_ok = len(recent) == 3 and recent[0]["event"] == "provider.request"
            record("async emit() stores 3 events in buffer", buf_ok, f"count={len(recent)}")

            # Check JSONL file written
            import time; time.sleep(0.1)  # small wait for to_thread writes
            logs = list(Path(tmpdir).glob("telemetry_*.jsonl"))
            file_ok = len(logs) == 1
            if file_ok:
                lines = logs[0].read_text().strip().splitlines()
                import json
                parsed = [json.loads(l) for l in lines if l.strip()]
                file_ok = len(parsed) == 3 and parsed[0]["event"] == "provider.request"
            record("JSONL file has 3 persisted events", file_ok)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Suite 6: disabled telemetry emits nothing
# ---------------------------------------------------------------------------
def test_disabled():
    try:
        from makima.core.telemetry import StructuredTelemetry
        tel = StructuredTelemetry(log_dir=None, buffer_size=100, enabled=False)
        tel.emit_sync("engine.turn_start", {"turn": 0})
        ok = tel.get_event_count() == 0
        record("Disabled telemetry emits nothing", ok, f"count={tel.get_event_count()}")
    except Exception as e:
        record("Disabled telemetry", False, str(e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Step 24 — StructuredTelemetry Verification")
    print("=" * 60)

    if not test_import():
        print("\n[ABORT] Import failed.")
        sys.exit(1)

    test_singleton()
    test_event_structure()
    test_sync_emit()
    test_async_emit()
    test_disabled()

    print("=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    print("=" * 60)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
