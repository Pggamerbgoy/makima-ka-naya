"""
Makima v2 — Persistent User Preference & Long-Term Memory Tools.
Architectural Pattern: Hermes-Style Autonomous Memory Tools operating on Markdown State (USER.md & MEMORY.md).
Zero-Bloat Guarantee: Pure stdlib + StateMemory delegation. Zero 1000-line heuristic regex engines.
"""

from __future__ import annotations

import logging
from typing import Any

from makima.memory.state import StateMemory
from makima.tools.registry import tool

logger = logging.getLogger("makima.tools.memory")


@tool(
    name="remember_user_preference",
    description="Records a permanent user preference, habit, working style, or profile trait into USER.md (e.g. 'Prefers dark mode', 'Always write code in Python', 'Preferred music app is Spotify').",
    tags=["memory", "preferences", "profile"],
)
def remember_user_preference(preference: str) -> dict[str, Any]:
    """
    Appends a new preference bullet point to ~/.makima/USER.md.

    Args:
        preference: The user preference, custom instruction, or personal habit to remember.
    """
    if not preference or not preference.strip():
        return {
            "success": False,
            "error": "Preference cannot be empty.",
        }

    sm = StateMemory()
    clean_pref = preference.strip()
    sm.append_user_profile(clean_pref)

    logger.info("Remembered user preference: %s", clean_pref)
    return {
        "success": True,
        "message": f"Successfully remembered user preference: '{clean_pref}'. It will be automatically injected into all future conversation contexts.",
        "preference": clean_pref,
        "file": str(sm.user_path),
    }


@tool(
    name="remember_fact",
    description="Records a permanent long-term knowledge fact, project rule, system insight, or environmental detail into MEMORY.md.",
    tags=["memory", "facts", "knowledge"],
)
def remember_fact(fact: str, category: str = "General") -> dict[str, Any]:
    """
    Appends a new knowledge fact under the specified category in ~/.makima/MEMORY.md.

    Args:
        fact: The statement, fact, or insight to record permanently.
        category: Optional category header (e.g. 'Project Rules', 'Architecture', 'Environment').
    """
    if not fact or not fact.strip():
        return {
            "success": False,
            "error": "Fact cannot be empty.",
        }

    sm = StateMemory()
    clean_fact = fact.strip()
    clean_cat = category.strip() if category else "General"
    sm.append_fact(clean_fact, category=clean_cat)

    logger.info("Remembered fact under [%s]: %s", clean_cat, clean_fact)
    return {
        "success": True,
        "message": f"Successfully recorded fact under '{clean_cat}': '{clean_fact}'.",
        "fact": clean_fact,
        "category": clean_cat,
        "file": str(sm.memory_path),
    }


@tool(
    name="forget_user_preference",
    description="Finds and deletes an outdated or revoked user preference from USER.md.",
    tags=["memory", "preferences", "cleanup"],
)
def forget_user_preference(search_text: str) -> dict[str, Any]:
    """
    Searches ~/.makima/USER.md for a preference containing search_text and removes it.

    Args:
        search_text: Substring identifying the preference to remove.
    """
    if not search_text or not search_text.strip():
        return {
            "success": False,
            "error": "search_text cannot be empty.",
        }

    sm = StateMemory()
    removed = sm.delete_user_preference(search_text.strip())
    if removed:
        logger.info("Forgot user preference matching: %s", search_text)
        return {
            "success": True,
            "message": f"Successfully removed user preference matching '{search_text}'.",
            "search_text": search_text,
        }
    return {
        "success": False,
        "message": f"No user preference found matching '{search_text}' in USER.md.",
        "search_text": search_text,
    }


@tool(
    name="forget_fact",
    description="Finds and deletes an outdated or incorrect knowledge fact from MEMORY.md.",
    tags=["memory", "facts", "cleanup"],
)
def forget_fact(search_text: str) -> dict[str, Any]:
    """
    Searches ~/.makima/MEMORY.md for a fact containing search_text and removes it.

    Args:
        search_text: Substring identifying the fact to remove.
    """
    if not search_text or not search_text.strip():
        return {
            "success": False,
            "error": "search_text cannot be empty.",
        }

    sm = StateMemory()
    removed = sm.delete_fact(search_text.strip())
    if removed:
        logger.info("Forgot fact matching: %s", search_text)
        return {
            "success": True,
            "message": f"Successfully removed fact matching '{search_text}'.",
            "search_text": search_text,
        }
    return {
        "success": False,
        "message": f"No fact found matching '{search_text}' in MEMORY.md.",
        "search_text": search_text,
    }


@tool(
    name="get_user_profile",
    description="Reads and returns the active user profile and preferences stored in USER.md.",
    tags=["memory", "preferences", "read"],
)
def get_user_profile() -> dict[str, Any]:
    """
    Reads the full content of ~/.makima/USER.md.
    """
    sm = StateMemory()
    content = sm.read_user_profile()
    return {
        "success": True,
        "content": content,
        "file": str(sm.user_path),
    }


@tool(
    name="get_memory_facts",
    description="Reads and returns all bulleted long-term knowledge facts stored in MEMORY.md.",
    tags=["memory", "facts", "read"],
)
def get_memory_facts() -> dict[str, Any]:
    """
    Reads all parsed facts from ~/.makima/MEMORY.md.
    """
    sm = StateMemory()
    facts = sm.get_facts_list()
    return {
        "success": True,
        "facts": facts,
        "count": len(facts),
        "file": str(sm.memory_path),
    }
