"""
Makima v2 — Autonomous Implicit Preference & Habit Learner.
Architectural Pattern: Hermes-Style Post-Turn Background Reflection & Heuristic Extraction.
Zero-Bloat Guarantee: Zero external dependencies, pure stdlib regex + StateMemory integration + optional fast LLM reflection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, List, Optional, Set, Tuple

from makima.memory.state import StateMemory
from makima.provider.adapters.base import Message
from makima.provider.router import ParetoRouter

logger = logging.getLogger("makima.memory.reflection")


class ImplicitPreferenceLearner:
    """
    Autonomously extracts and persists implicit user preferences, habits,
    communication styles, and corrections from conversation turns into ~/.makima/USER.md.
    
    Operates in two modes:
      1. Fast Heuristic Extraction (0ms latency, zero API calls, deterministic regex).
      2. Asynchronous LLM Reflection (background async task triggered on correction signals).
    """

    # Rule patterns for direct user preferences and behavioral directives
    PATTERNS: List[Tuple[re.Pattern, str]] = [
        # Corrections: "No, don't use X, use Y instead" / "Don't use X, use Y"
        (
            re.compile(
                r"(?:no|nahi|wrong)?\s*,?\s*(?:don't|do not|mat)\s+(?:use|open|run|do)\s+([^,.\n]+?)(?:,?\s*(?:use|open|run|do|karo)\s+([^,.\n]+?)(?:\s+instead)?)?$",
                re.IGNORECASE,
            ),
            "correction",
        ),
        # Direct Preference: "I prefer X", "I prefer using X", "I like X"
        (
            re.compile(
                r"(?:i\s+prefer|i\s+like|i\s+always\s+prefer|mujhe\s+pasand\s+hai)\s+(?:to\s+use\s+|using\s+|to\s+have\s+)?([^,.\n]+)",
                re.IGNORECASE,
            ),
            "preference",
        ),
        # Directives: "Always do X", "Always use X", "Hamesha X use karo"
        (
            re.compile(
                r"(?:always|hamesha)\s+([^,.\n]+)",
                re.IGNORECASE,
            ),
            "always",
        ),
        # Negative directives: "Never do X", "Never use X", "Kabhi mat karo"
        (
            re.compile(
                r"(?:never|kabhi\s+mat)\s+([^,.\n]+)",
                re.IGNORECASE,
            ),
            "never",
        ),
        # Temporal shifts: "From now on, do X", "Ab se X karo"
        (
            re.compile(
                r"(?:from\s+now\s+on|ab\s+se)\s*,?\s*([^,.\n]+)",
                re.IGNORECASE,
            ),
            "from_now_on",
        ),
        # Identity / Name: "My name is X", "Call me X", "Mera naam X hai"
        (
            re.compile(
                r"(?:my\s+name\s+is|call\s+me|mera\s+naam)\s+([A-Za-z0-9_]+)",
                re.IGNORECASE,
            ),
            "name",
        ),
        # Natural Consumption/Tool Habits: "mai anime miruro.ru pe dekhta hu", "mai music spotify par sunta hu"
        (
            re.compile(
                r"(?:mai|main)\s+([^,.\n]+?)\s+([a-zA-Z0-9_.\-]+(?:\.[a-zA-Z]{2,})?)\s+(?:pe|par|me|mein)\s+(?:dekhta|dekhti|sunta|sunti|padhta|padhti|likhta|likhti|chalaata|chalaati|karta|karti)\s+hu(?:\s+(?:for\s+now|abhi\s+ke\s+liye))?",
                re.IGNORECASE,
            ),
            "consumption_habit_1",
        ),
        (
            re.compile(
                r"(?:mai|main)\s+([a-zA-Z0-9_.\-]+(?:\.[a-zA-Z]{2,})?)\s+(?:pe|par|me|mein)\s+([^,.\n]+?)\s+(?:dekhta|dekhti|sunta|sunti|padhta|padhti|likhta|likhti|chalaata|chalaati|karta|karti)\s+hu(?:\s+(?:for\s+now|abhi\s+ke\s+liye))?",
                re.IGNORECASE,
            ),
            "consumption_habit_2",
        ),
    ]

    # Class-level deduplication guard — prevents race condition when multiple
    # background asyncio tasks fire simultaneously and all read USER.md before
    # any write completes (root cause of duplicate entries like "9anime x9")
    _seen_prefs: Set[str] = set()
    _write_lock: Optional[asyncio.Lock] = None
    _write_lock_loop: Optional[Any] = None

    @classmethod
    def _get_write_lock(cls) -> asyncio.Lock:
        """Lazily creates the asyncio.Lock, re-creating if event loop has changed."""
        try:
            curr_loop = asyncio.get_running_loop()
        except RuntimeError:
            curr_loop = None

        if cls._write_lock is None or cls._write_lock_loop != curr_loop:
            cls._write_lock = asyncio.Lock()
            cls._write_lock_loop = curr_loop
        return cls._write_lock

    # Transient command blacklist — skip temporary commands that look like preferences
    TRANSIENT_VERBS = {
        "click", "scroll", "read", "fetch", "get", "inspect", "check", "verify",
        "calculate", "delete", "remove", "close", "kill", "terminate", "press"
    }

    # Transient phrases that contain words like 'no' or 'stop' but are NOT persistent preferences
    TRANSIENT_PHRASES = (
        "stop the music",
        "stop music",
        "stop playing",
        "stop video",
        "stop timer",
        "stop alarm",
        "stop recording",
        "no problem",
        "no worries",
        "no thanks",
        "no thank you",
        "no need",
        "no idea",
        "no doubt",
    )

    # Word-bounded semantic cues for nuanced English & Hinglish preferences/corrections/styles
    LLM_REFLECTION_SIGNAL_RE = re.compile(
        r"\b(?:"
        r"prefer|prefers|preferred|rather|instead|actually|wrong|always|never|"
        r"default|favorite|favourite|usually|normally|habit|style|tone|format|"
        r"concise|brief|detailed|hinglish|hindi|english|"
        r"pasand|hamesha|kabhi|chahiye|rakhna|rakho|dekhta|dekhti|sunta|sunti|chalaata|chalaati|"
        r"don't|dont|do\s+not|avoid|switch\s+to|"
        r"mat\s+(?:karo|karna|kholo|kholna|chala|chalana|likho|likhna|bolo|bolna|use)|"
        r"(?:diya|kiya|bola|likha|bheja|use\s+kiya)\s+karo|"
        r"(?:no|nahi)\s*,\s*\w+"
        r")\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        state_memory: Optional[StateMemory] = None,
        router: Optional[ParetoRouter] = None,
        enable_llm_reflection: bool = True,
    ) -> None:
        self.state_memory = state_memory or StateMemory()
        self.router = router
        self.enable_llm_reflection = enable_llm_reflection


    def extract_heuristically(self, user_message: str) -> Optional[str]:
        """
        Fast regex-based heuristic extractor.
        Returns a clean preference statement string, or None if no persistent preference detected.
        """
        if not user_message or len(user_message.strip()) < 4:
            return None

        clean_text = user_message.strip()

        for pattern, pattern_type in self.PATTERNS:
            match = pattern.search(clean_text)
            if not match:
                continue

            groups = [g.strip() for g in match.groups() if g]
            if not groups:
                continue

            # Case: Correction "don't use X, use Y"
            if pattern_type == "correction":
                x_val = groups[0]
                y_val = groups[1] if len(groups) > 1 else None
                # Check for transient commands (e.g. "don't click that")
                first_word = x_val.split()[0].lower() if x_val.split() else ""
                if first_word in self.TRANSIENT_VERBS:
                    continue
                if y_val:
                    return f"Prefers {y_val} instead of {x_val}"
                else:
                    return f"Avoid using {x_val}"

            # Case: Direct Preference "I prefer X"
            elif pattern_type == "preference":
                target = groups[0]
                first_word = target.split()[0].lower() if target.split() else ""
                if first_word in self.TRANSIENT_VERBS:
                    continue
                return f"Prefers {target}"

            # Case: "Always do X"
            elif pattern_type == "always":
                target = groups[0]
                return f"Always {target}"

            # Case: "Never do X"
            elif pattern_type == "never":
                target = groups[0]
                return f"Never {target}"

            # Case: "From now on, do X"
            elif pattern_type == "from_now_on":
                target = groups[0]
                return f"Instruction: {target}"

            # Case: "My name is X"
            elif pattern_type == "name":
                name = groups[0]
                return f"Name is {name}"

            # Case: Consumption habit "mai anime miruro.ru pe dekhta hu"
            elif pattern_type == "consumption_habit_1":
                cat = groups[0].strip()
                platform = groups[1].strip()
                return f"Watches/uses {platform} for {cat}"

            # Case: Consumption habit "mai miruro.ru pe anime dekhta hu"
            elif pattern_type == "consumption_habit_2":
                platform = groups[0].strip()
                cat = groups[1].strip()
                return f"Watches/uses {platform} for {cat}"

        return None

    def is_already_known(self, candidate_pref: str) -> bool:
        """
        Deduplication check: checks if candidate_pref is already reflected in USER.md.
        """
        try:
            profile = self.state_memory.read_user_profile().lower()
        except Exception:
            return False

        norm_candidate = candidate_pref.lower().strip()
        # Direct substring match
        if norm_candidate in profile:
            return True

        # Token overlap match (>75% token overlap with an existing bullet)
        cand_tokens = set(re.findall(r"\w+", norm_candidate)) - {"prefers", "always", "never", "use", "instead", "of"}
        if not cand_tokens:
            return False

        for line in profile.splitlines():
            line_str = line.strip().lstrip("-* ").strip()
            if not line_str:
                continue
            line_tokens = set(re.findall(r"\w+", line_str))
            overlap = cand_tokens & line_tokens
            if len(overlap) >= len(cand_tokens) * 0.75:
                return True

        return False

    async def reflect_with_llm(
        self,
        user_message: str,
        assistant_response: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[str]:
        """
        Asynchronous LLM-based reflection fallback for ambiguous corrections or nuanced phrasing.
        Invoked only when user message exhibits correction/preference signals but heuristics didn't match.
        """
        if not self.enable_llm_reflection or not self.router or not user_message:
            return None

        lower_msg = user_message.lower().strip()
        if any(tp in lower_msg for tp in self.TRANSIENT_PHRASES):
            return None

        if not self.LLM_REFLECTION_SIGNAL_RE.search(user_message):
            return None


        system_prompt = (
            "You are Makima's User Preference Analyzer. "
            "Analyze the conversation turn to determine if the user stated a persistent personal preference, "
            "habit, preferred tool/language, or behavioral correction for the AI assistant.\n"
            "Rules:\n"
            "1. Ignore one-off, transient task commands (e.g. 'read test.py', 'click button 2', 'what is time').\n"
            "2. Identify ONLY lasting user preferences (e.g. 'User prefers Brave browser', 'User wants brief answers').\n"
            "3. Output strictly valid JSON: {\"has_preference\": boolean, \"preference\": string | null}."
        )

        prompt = f"User said: {user_message}\nAssistant replied: {(assistant_response or '')[:300]}"

        try:
            call_kwargs = {
                "task": "fast_chat",
                "messages": [Message(role="user", content=prompt)],
                "system_prompt": system_prompt,
                "temperature": 0.0,
                "max_tokens": 150,
            }
            if model:
                call_kwargs["model"] = model
            res = await self.router.execute_with_fallback(**call_kwargs)
            content = res.content.strip()
            # Extract JSON block
            if "{" in content and "}" in content:
                json_str = content[content.find("{") : content.rfind("}") + 1]
                data = json.loads(json_str)
                if data.get("has_preference") and data.get("preference"):
                    return str(data["preference"]).strip()
        except Exception as e:
            logger.debug(f"LLM preference reflection skipped: {e}")

        return None

    async def learn_from_turn(
        self,
        user_message: str,
        assistant_response: Optional[str] = None,
    ) -> Optional[str]:
        """
        Processes a finished turn. If a new persistent preference is detected,
        appends it cleanly to USER.md and returns the learned preference string.
        """
        # 1. Try fast heuristic first
        learned = self.extract_heuristically(user_message)

        # 2. If heuristic didn't match, try LLM reflection
        if not learned:
            learned = await self.reflect_with_llm(user_message, assistant_response)

        if not learned:
            return None

        # 3. Normalize for deduplication
        norm = learned.lower().strip()

        # 3a. Fast in-memory check — catches concurrent background tasks that
        #     haven't written to disk yet but are already in-flight
        if norm in self.__class__._seen_prefs:
            logger.debug(f"Skipping in-flight duplicate preference: {learned}")
            return None

        # 3b. Disk-based deduplication check
        if self.is_already_known(learned):
            logger.debug(f"Skipping already-known preference: {learned}")
            self.__class__._seen_prefs.add(norm)
            return None

        # 4. Serialize write with asyncio lock — prevents two concurrent tasks
        #    from both passing the checks above and writing the same entry twice
        async with self.__class__._get_write_lock():
            # Re-check inside lock: another task may have written while we waited
            if norm in self.__class__._seen_prefs:
                logger.debug(f"Skipping duplicate (acquired after lock): {learned}")
                return None

            # Mark as seen BEFORE writing so any other waiting task skips it
            self.__class__._seen_prefs.add(norm)

            try:
                # Contradiction cleanup: "Prefers Y instead of X" -> remove old X preference
                if " instead of " in norm:
                    old_target = learned.split(" instead of ")[-1].strip()
                    if old_target:
                        await asyncio.to_thread(self.state_memory.delete_user_preference, old_target)
                elif norm.startswith("name is "):
                    await asyncio.to_thread(self.state_memory.delete_user_preference, "**Name**:")
                    await asyncio.to_thread(self.state_memory.delete_user_preference, "Name is ")

                await self.state_memory.append_user_profile_async(learned)
                logger.info(f"Autonomously learned and saved user preference: '{learned}'")
                return learned
            except Exception as e:
                # On write failure, remove from seen so it can be retried next session
                self.__class__._seen_prefs.discard(norm)
                logger.error(f"Failed to persist learned preference '{learned}': {e}")
                return None

    def ingest_habits(self, habits_json_path) -> int:
        """
        Reads HABITS.json from the Sentinel engine and appends confirmed habits
        as preference entries in USER.md via StateMemory.
        Synchronous — safe to call from APScheduler background jobs.
        Returns the count of newly written habit entries.
        """
        import json as _json
        from pathlib import Path as _Path

        path = _Path(habits_json_path)
        if not path.exists():
            logger.debug("ingest_habits: HABITS.json not found at %s", path)
            return 0

        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("ingest_habits: Could not read HABITS.json: %s", exc)
            return 0

        written = 0
        try:
            profile_lines = self.state_memory.read_user_profile().splitlines()
        except Exception:
            profile_lines = []

        for habit in data.get("habits", []):
            if not habit.get("confirmed"):
                continue
            label = habit.get("label", "")
            apps = habit.get("apps", [])
            weekdays = habit.get("weekdays", [])
            hour_start = habit.get("hour_start", -1)

            if not label:
                continue

            # Build a human-readable preference string
            days_str = ", ".join(weekdays) if weekdays else "weekdays"
            app_str = apps[0].replace(".exe", "") if apps else "unknown app"
            pref = f"Daily habit: Uses {app_str} on {days_str} around {hour_start:02d}:00 ({label})"

            norm = pref.lower().strip()
            if norm in self.__class__._seen_prefs:
                continue

            # Check if this specific habit (app + hour) already exists in USER.md
            already_present = False
            for line in profile_lines:
                ll = line.lower()
                if "daily habit" in ll and app_str.lower() in ll and f"{hour_start:02d}:00" in ll:
                    already_present = True
                    break

            if already_present:
                self.__class__._seen_prefs.add(norm)
                continue

            try:
                self.state_memory.append_user_profile(pref)
                self.__class__._seen_prefs.add(norm)
                profile_lines.append(f"- {pref}")
                logger.info("ingest_habits: Persisted habit preference — %s", pref)
                written += 1
            except Exception as exc:
                logger.error("ingest_habits: Failed to write '%s': %s", pref, exc)

        return written

