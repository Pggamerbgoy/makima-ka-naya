"""
Makima Sentinel — Proactive Decision Brain.
Architectural Pattern: 5-minute polling daemon with sequential decision gates.
Anti-fatigue: 30-min cooldown between toasts. DND: fullscreen/game guard.
Two triggers: User Return (idle > 5 min then active) and Habit Window (±15 min).
Brain call: POST to Makima brain HTTP endpoint for suggestion text.
Toast: win11toast with [Haan, Karo] / [Abhi Nahi] buttons.
Rejection: snooze_until = now + 4 hours.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("makima.sentinel.proactive_daemon")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
COOLDOWN_MINUTES = 30
SNOOZE_HOURS = 4
HABIT_WINDOW_MINUTES = 15
BRAIN_URL = "http://127.0.0.1:8000"
BRAIN_TIMEOUT_S = 10.0


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _get_data_dir() -> Path:
    from makima.config import get_settings
    return Path(get_settings().app.data_dir).expanduser()


def _load_state(data_dir: Path) -> Dict[str, Any]:
    """Load sentinel_state.json; returns empty defaults if missing/corrupt."""
    state_path = data_dir / "sentinel_state.json"
    defaults: Dict[str, Any] = {
        "last_notification_ts": None,
        "snooze_until": None,
        "rejection_log": [],
    }
    if not state_path.exists():
        return defaults
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        defaults.update(data)
        return defaults
    except Exception:
        return defaults


def _save_state(data_dir: Path, state: Dict[str, Any]) -> None:
    state_path = data_dir / "sentinel_state.json"
    try:
        state_path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.error("Failed to save sentinel_state.json: %s", exc)


# ---------------------------------------------------------------------------
# Decision gate helpers
# ---------------------------------------------------------------------------

def _gate_anti_fatigue(state: Dict[str, Any], now: datetime) -> bool:
    """Returns True (SKIP) if last notification was < COOLDOWN_MINUTES ago."""
    last_ts = state.get("last_notification_ts")
    if not last_ts:
        return False
    try:
        last_dt = datetime.fromisoformat(last_ts)
        if (now - last_dt).total_seconds() < COOLDOWN_MINUTES * 60:
            logger.debug("Proactive daemon: anti-fatigue gate blocked (cooldown active)")
            return True
    except Exception:
        pass
    return False


def _gate_snooze(state: Dict[str, Any], now: datetime) -> bool:
    """Returns True (SKIP) if user snoozed and snooze window hasn't expired."""
    snooze_until = state.get("snooze_until")
    if not snooze_until:
        return False
    try:
        snooze_dt = datetime.fromisoformat(snooze_until)
        if now < snooze_dt:
            logger.debug("Proactive daemon: snooze gate blocked until %s", snooze_until)
            return True
    except Exception:
        pass
    return False


def _gate_dnd(snapshot: Dict[str, Any]) -> bool:
    """Returns True (SKIP) if user is in fullscreen or a game/DND process."""
    from makima.sentinel.observer import is_dnd_process
    if snapshot.get("fullscreen"):
        logger.debug("Proactive daemon: DND gate blocked (fullscreen active)")
        return True
    proc = snapshot.get("active_process", "")
    if is_dnd_process(proc):
        logger.debug("Proactive daemon: DND gate blocked (game process: %s)", proc)
        return True
    return False


def _check_user_return(prev_snapshot: Optional[Dict[str, Any]], curr_snapshot: Dict[str, Any]) -> bool:
    """
    Trigger A — User Return:
    Previous snapshot was idle > 5 min, current is idle < 10 sec.
    """
    if prev_snapshot is None:
        return False
    prev_idle = prev_snapshot.get("user_idle_seconds", 0)
    curr_idle = curr_snapshot.get("user_idle_seconds", 999)
    triggered = prev_idle > 300 and curr_idle < 10
    if triggered:
        logger.info("Proactive daemon: Trigger A (User Return) fired — was idle %.0fs, now active", prev_idle)
    return triggered


def _check_habit_window(habits: List[Dict[str, Any]], now: datetime) -> Optional[Dict[str, Any]]:
    """
    Trigger B — Habit Window:
    Fires if current time falls within:
      1. ±HABIT_WINDOW_MINUTES (15m) before habit start (preparation moment)
      2. OR actively inside the habit duration [hour_start, hour_end)
    """
    now_min = now.hour * 60 + now.minute
    weekday = now.strftime("%A")

    for habit in habits:
        habit_days = habit.get("weekdays", [])
        if habit_days and weekday not in habit_days:
            continue

        h_start = habit.get("hour_start", -1)
        if h_start < 0:
            continue
        h_end = habit.get("hour_end", h_start + 1)

        start_min = h_start * 60
        end_min = h_end * 60

        # Trigger if within 15 min prior to start or inside the active habit window
        if (start_min - HABIT_WINDOW_MINUTES <= now_min < end_min):
            logger.info(
                "Proactive daemon: Trigger B (Habit Window) fired — habit: %s",
                habit.get("label", habit.get("id", "unknown")),
            )
            return habit
    return None


# ---------------------------------------------------------------------------
# Brain call
# ---------------------------------------------------------------------------

def _build_suggestion(trigger_type: str, context: Dict[str, Any]) -> str:
    """
    Builds a suggestion message by calling Makima brain HTTP endpoint.
    Falls back to a default message if brain is unavailable.
    """
    import httpx

    app_label = context.get("app_label", context.get("active_process", "your app"))
    habit_label = context.get("habit_label", "your routine")
    hour = context.get("hour", datetime.now().hour)

    default_msg = (
        f"Aapka {habit_label} ka time ho gaya hai! "
        f"Kya main {app_label} open karke workspace set kar doon?"
        if trigger_type == "habit_window"
        else "Welcome back! Kya main aapka workspace set up kar doon?"
    )

    try:
        prompt = (
            f"User context: trigger={trigger_type}, active_app={app_label}, "
            f"habit={habit_label}, hour={hour}. "
            f"In ONE short friendly Hinglish sentence (max 15 words), suggest a proactive action "
            f"Makima could do for the user right now (e.g. open apps, play music)."
        )
        payload = {
            "message": prompt,
            "user_id": "sentinel_daemon",
            "session_id": "proactive",
        }
        with httpx.Client(timeout=BRAIN_TIMEOUT_S) as client:
            resp = client.post(f"{BRAIN_URL}/api/chat", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                suggestion = (
                    data.get("response")
                    or data.get("message")
                    or data.get("content")
                    or ""
                ).strip()
                if suggestion and len(suggestion) > 5:
                    return suggestion
    except Exception as exc:
        logger.debug("Brain call failed (using default): %s", exc)

    return default_msg


# ---------------------------------------------------------------------------
# Toast dispatch
# ---------------------------------------------------------------------------

# Module-level ref to the last snapshot for User Return detection
_prev_snapshot: Optional[Dict[str, Any]] = None


def _dispatch_toast(
    suggestion: str,
    habit_id: Optional[str],
    habit_apps: List[str],
    data_dir: Path,
) -> None:
    """
    Displays a Windows Action Center toast alert with [Haan, Karo] and [Abhi Nahi] action buttons.
    Blocks inside its dedicated background worker thread until user interacts or toast times out.
    Handles:
      - [Haan, Karo]: Executes the proactive setup (focuses/launches target app).
      - [Abhi Nahi]: Snoozes proactive alerts for SNOOZE_HOURS (4h) and records rejection.
      - Dismiss/Timeout: Gracefully finishes without false snooze.
    """
    import win11toast

    handled_lock = threading.Lock()
    handled = False

    def _handle_response(arg_str: str) -> None:
        nonlocal handled
        with handled_lock:
            if handled:
                return
            handled = True

        clean_arg = (arg_str or "").lower()
        if "abhi nahi" in clean_arg:
            state = _load_state(data_dir)
            snooze_time = (datetime.now() + timedelta(hours=SNOOZE_HOURS)).isoformat(timespec="seconds")
            state["snooze_until"] = snooze_time
            if habit_id:
                state.setdefault("rejection_log", []).append({
                    "habit_id": habit_id,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                })
            _save_state(data_dir, state)
            logger.info("Proactive toast snoozed for %d hours by user.", SNOOZE_HOURS)

        elif "haan" in clean_arg or "karo" in clean_arg:
            logger.info("Proactive toast accepted by user for habit: %s", habit_id)
            if habit_apps:
                target_app = habit_apps[0]
                try:
                    from makima.tools.os.apps import launch_app
                    from makima.tools.os.windows import focus_window

                    focused = focus_window(title_query=target_app.replace(".exe", ""))
                    if not focused.get("success"):
                        launch_app(app_name=target_app)
                        logger.info("Proactively launched app: %s", target_app)
                    else:
                        logger.info("Proactively focused app: %s", target_app)
                except Exception as exc:
                    logger.warning("Could not execute proactive app launch: %s", exc)

    def _on_click(args=None):
        arg = ""
        if isinstance(args, dict):
            arg = str(args.get("arguments", ""))
        elif isinstance(args, str):
            arg = args
        _handle_response(arg)

    def _on_dismissed(reason=None):
        logger.debug("Proactive toast dismissed or timed out: %s", reason)

    try:
        res = win11toast.toast(
            "Makima 🤖",
            suggestion,
            buttons=["Haan, Karo", "Abhi Nahi"],
            on_click=_on_click,
            on_dismissed=_on_dismissed,
        )
        if isinstance(res, dict):
            _handle_response(str(res.get("arguments", "")))
    except Exception as exc:
        logger.debug("Toast with callbacks had issue (%s); falling back to direct win11toast.", exc)
        try:
            res2 = win11toast.toast("Makima 🤖", suggestion, buttons=["Haan, Karo", "Abhi Nahi"])
            if isinstance(res2, dict):
                _handle_response(str(res2.get("arguments", "")))
        except Exception as exc2:
            logger.warning("Toast dispatch failed entirely: %s", exc2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def evaluate_and_act() -> None:
    """
    Main proactive daemon entry point. Called by APScheduler every 5 minutes.
    Sequential gate logic → trigger detection → brain call → toast.
    """
    global _prev_snapshot

    now = datetime.now()
    data_dir = _get_data_dir()
    state = _load_state(data_dir)

    # --- Gate 1: Anti-fatigue ---
    if _gate_anti_fatigue(state, now):
        return

    # --- Gate 2: Snooze ---
    if _gate_snooze(state, now):
        return

    # --- Get latest snapshot for DND + trigger checks ---
    obs_path = data_dir / "observations.jsonl"
    curr_snapshot: Dict[str, Any] = {}
    if obs_path.exists():
        try:
            lines = obs_path.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines):
                line = line.strip()
                if line:
                    curr_snapshot = json.loads(line)
                    break
        except Exception:
            pass

    # --- Gate 3: DND check ---
    if curr_snapshot and _gate_dnd(curr_snapshot):
        _prev_snapshot = curr_snapshot
        return

    # --- Trigger detection ---
    trigger_type: Optional[str] = None
    matched_habit: Optional[Dict[str, Any]] = None
    context: Dict[str, Any] = {
        "active_process": curr_snapshot.get("active_process", ""),
        "app_label": curr_snapshot.get("active_process", "your workspace"),
        "hour": now.hour,
        "habit_label": "your routine",
    }

    # Trigger A: User Return
    if _check_user_return(_prev_snapshot, curr_snapshot):
        trigger_type = "user_return"

    # Trigger B: Habit Window (only if Trigger A didn't fire)
    if trigger_type is None:
        from makima.sentinel.habit_engine import load_habits
        habits = load_habits(data_dir)
        matched_habit = _check_habit_window(habits, now)
        if matched_habit:
            trigger_type = "habit_window"
            context["habit_label"] = matched_habit.get("label", "your routine")
            context["app_label"] = matched_habit.get("apps", [context["active_process"]])[0]

    # Update prev snapshot regardless
    _prev_snapshot = curr_snapshot if curr_snapshot else _prev_snapshot

    if trigger_type is None:
        logger.debug("Proactive daemon: no trigger fired this cycle.")
        return

    # --- Build suggestion via brain ---
    suggestion = _build_suggestion(trigger_type, context)

    # --- Update state: mark notification time ---
    state["last_notification_ts"] = now.isoformat(timespec="seconds")
    _save_state(data_dir, state)

    # --- Dispatch toast in background thread (non-blocking) ---
    habit_id = matched_habit.get("id") if matched_habit else None
    habit_apps = matched_habit.get("apps", []) if matched_habit else []
    toast_thread = threading.Thread(
        target=_dispatch_toast,
        args=(suggestion, habit_id, habit_apps, data_dir),
        name="sentinel-toast",
        daemon=True,
    )
    toast_thread.start()
    logger.info("Proactive daemon: toast dispatched (trigger=%s)", trigger_type)
