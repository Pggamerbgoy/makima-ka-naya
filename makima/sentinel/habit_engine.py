"""
Makima Sentinel — Habit Pattern Detector.
Architectural Pattern: Daily cron job that reads observations.jsonl, finds
3-day confirmed patterns, and writes HABITS.json. Feeds ImplicitPreferenceLearner.
Runs at 3 AM daily via APScheduler cron trigger.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("makima.sentinel.habit_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONFIRMATION_DAYS = 3  # Minimum distinct days to confirm a habit
HOUR_BUCKET_SIZE = 1   # Group by single hour (can widen to 2 if too noisy)
MAX_AGE_DAYS = 30      # Look back up to 30 days for habit pattern analysis



# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_data_dir() -> Path:
    from makima.config import get_settings
    return Path(get_settings().app.data_dir).expanduser()


def _load_observations(obs_path: Path) -> List[Dict[str, Any]]:
    """Read observations.jsonl, skipping malformed lines and entries older than MAX_AGE_DAYS."""
    if not obs_path.exists():
        return []

    cutoff = datetime.now() - timedelta(days=MAX_AGE_DAYS)
    rows: List[Dict[str, Any]] = []
    try:
        for line in obs_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ts = datetime.fromisoformat(obj.get("ts", ""))
                if ts >= cutoff:
                    rows.append(obj)
            except Exception:
                continue
    except Exception as exc:
        logger.warning("Could not read observations.jsonl: %s", exc)
    return rows


def _build_habit_id(weekday: str, hour: int, process: str) -> str:
    """Stable, filesystem-safe ID for a habit pattern."""
    clean_proc = process.replace(".exe", "").replace(" ", "_").lower()
    return f"{weekday[:3].lower()}_{hour:02d}h_{clean_proc}"


def _app_label(process: str) -> str:
    """Human-readable app label from process name."""
    labels = {
        "code.exe": "VS Code",
        "windowsterminal.exe": "Terminal",
        "chrome.exe": "Chrome",
        "msedge.exe": "Edge",
        "firefox.exe": "Firefox",
        "spotify.exe": "Spotify",
        "discord.exe": "Discord",
        "notion.exe": "Notion",
        "obsidian.exe": "Obsidian",
        "pycharm64.exe": "PyCharm",
        "idea64.exe": "IntelliJ",
    }
    return labels.get(process.lower(), process.replace(".exe", ""))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_habit_analysis() -> Dict[str, Any]:
    """
    Reads observations.jsonl, detects confirmed habits (≥3 distinct days),
    writes HABITS.json, and feeds ImplicitPreferenceLearner.
    Called by APScheduler daily at 3:00 AM.
    """
    data_dir = _get_data_dir()
    obs_path = data_dir / "observations.jsonl"
    habits_path = data_dir / "HABITS.json"

    observations = _load_observations(obs_path)
    if not observations:
        logger.info("HabitEngine: No observations to analyze.")
        return {"habits_confirmed": 0, "analyzed": 0}

    # -----------------------------------------------------------------------
    # Group by (weekday, hour_bucket, active_process) → set of distinct dates
    # -----------------------------------------------------------------------
    # key: (weekday, hour, process_name)
    # value: set of date strings (distinct days the pattern appeared)
    pattern_dates: Dict[tuple, set] = defaultdict(set)

    for obs in observations:
        proc = obs.get("active_process", "").strip()
        if not proc:
            continue
        # Skip idle snapshots (user away from desk > 5 min)
        if obs.get("user_idle_seconds", 0) > 300:
            continue

        try:
            ts = datetime.fromisoformat(obs["ts"])
        except Exception:
            continue

        weekday = ts.strftime("%A")
        hour = ts.hour
        day_str = ts.strftime("%Y-%m-%d")
        key = (weekday, hour, proc)
        pattern_dates[key].add(day_str)

    # -----------------------------------------------------------------------
    # Identify confirmed habits (appeared on ≥ CONFIRMATION_DAYS distinct days)
    # -----------------------------------------------------------------------
    confirmed: List[Dict[str, Any]] = []

    # Load existing habits to preserve metadata
    existing_habits: Dict[str, Dict[str, Any]] = {}
    if habits_path.exists():
        try:
            data = json.loads(habits_path.read_text(encoding="utf-8"))
            for h in data.get("habits", []):
                existing_habits[h["id"]] = h
        except Exception:
            pass

    for (weekday, hour, process), day_set in pattern_dates.items():
        if len(day_set) < CONFIRMATION_DAYS:
            continue

        habit_id = _build_habit_id(weekday, hour, process)
        confidence = min(1.0, round(len(day_set) / max(MAX_AGE_DAYS, 1), 2))

        # Preserve existing metadata if available
        existing = existing_habits.get(habit_id, {})

        habit: Dict[str, Any] = {
            "id": habit_id,
            "label": f"{_app_label(process)} on {weekday}s ~{hour:02d}:00",
            "weekdays": existing.get("weekdays", [weekday]),
            "hour_start": hour,
            "hour_end": hour + 1,
            "apps": [process],
            "confidence": confidence,
            "confirmed": True,
            "last_updated": date.today().isoformat(),
            "sample_days": sorted(day_set),
        }

        # Merge weekdays if we've seen this hour/process on multiple days
        confirmed.append(habit)

    # -----------------------------------------------------------------------
    # Write HABITS.json
    # -----------------------------------------------------------------------
    habits_data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "habits": confirmed,
    }
    try:
        habits_path.write_text(
            json.dumps(habits_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("HabitEngine: Wrote %d confirmed habit(s) to HABITS.json", len(confirmed))
    except Exception as exc:
        logger.error("HabitEngine: Failed to write HABITS.json: %s", exc)
        return {"habits_confirmed": 0, "analyzed": len(observations), "error": str(exc)}

    # -----------------------------------------------------------------------
    # Feed ImplicitPreferenceLearner — only if habits are newly confirmed
    # -----------------------------------------------------------------------
    if confirmed:
        _feed_preference_learner(confirmed, data_dir)

    return {"habits_confirmed": len(confirmed), "analyzed": len(observations)}


def _feed_preference_learner(habits: List[Dict[str, Any]], data_dir: Path) -> None:
    """
    Translates confirmed habits into USER.md preference entries via
    ImplicitPreferenceLearner.ingest_habits() — non-blocking, best-effort.
    """
    try:
        from makima.memory.reflection import ImplicitPreferenceLearner
        from makima.memory.state import StateMemory

        learner = ImplicitPreferenceLearner(state_memory=StateMemory())
        learner.ingest_habits(data_dir / "HABITS.json")
    except Exception as exc:
        logger.debug("HabitEngine: Could not feed ImplicitPreferenceLearner: %s", exc)


def load_habits(data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Utility: load current confirmed habits from HABITS.json.
    Used by proactive_daemon to check trigger windows.
    """
    if data_dir is None:
        data_dir = _get_data_dir()
    habits_path = data_dir / "HABITS.json"
    if not habits_path.exists():
        return []
    try:
        data = json.loads(habits_path.read_text(encoding="utf-8"))
        return [h for h in data.get("habits", []) if h.get("confirmed")]
    except Exception:
        return []
