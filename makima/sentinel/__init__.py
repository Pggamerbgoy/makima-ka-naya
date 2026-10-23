"""
Makima Sentinel — Proactive Habit & Behavioral Observer Engine.
Silently watches user activity, learns daily patterns, and proactively
assists without waiting for explicit commands.
"""

from makima.sentinel.observer import take_snapshot, is_dnd_process
from makima.sentinel.habit_engine import run_habit_analysis, load_habits
from makima.sentinel.proactive_daemon import evaluate_and_act
from makima.sentinel.event_daemon import (
    SentinelEventDaemon,
    ListeningDevilDaemon,
    get_sentinel_daemon,
    StackTraceAnalyzer,
    StackTraceInfo,
    FileAlertEvent,
    ResourceAlertEvent,
)

__all__ = [
    "take_snapshot",
    "is_dnd_process",
    "run_habit_analysis",
    "load_habits",
    "evaluate_and_act",
    "SentinelEventDaemon",
    "ListeningDevilDaemon",
    "get_sentinel_daemon",
    "StackTraceAnalyzer",
    "StackTraceInfo",
    "FileAlertEvent",
    "ResourceAlertEvent",
]

