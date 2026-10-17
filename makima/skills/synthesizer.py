"""
Makima v2 — Skill Synthesizer Tool.
Architectural Pattern: Tool-level generation of structured Markdown skills with YAML frontmatter.
Rule 6: Clean, modular Makima v2 code. Zero copy-paste from v1.
Rule 7: Library-first using pathlib, yaml, and pydantic.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import yaml

from makima.skills.loader import get_skills_loader
from makima.tools.registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="save_learned_skill",
    description="Saves and registers a new learned skill as a structured Markdown file with YAML frontmatter.",
    tags=["skills", "learning", "system"],
)
def save_learned_skill(
    name: str,
    description: str,
    instructions: str,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Saves a newly acquired or refined procedural skill into the Makima skills repository.

    Args:
        name: Unique skill identifier (alphanumeric, dashes, underscores only).
        description: Brief summary of what the skill accomplishes.
        instructions: Detailed step-by-step procedural guidelines in Markdown format.
        tags: Optional category tags for skill discovery.
    """
    clean_name = name.strip()

    # Validate skill name
    if not clean_name or not re.match(r"^[a-zA-Z0-9_-]+$", clean_name):
        return {
            "success": False,
            "error": (
                f"Invalid skill name '{name}'. "
                "Name must contain only alphanumeric characters, dashes, and underscores."
            ),
        }

    loader = get_skills_loader()
    target_dir = loader.skills_dir / clean_name

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / "SKILL.md"

        meta = {
            "name": clean_name,
            "description": description.strip(),
            "tags": [t.strip() for t in tags] if tags else [],
            "version": "1.0.0",
        }

        yaml_front = yaml.safe_dump(meta, sort_keys=False).strip()
        markdown_content = f"---\n{yaml_front}\n---\n\n{instructions.strip()}\n"

        file_path.write_text(markdown_content, encoding="utf-8")

        # Reload skills loader cache so new skill is instantly queryable
        total_skills = loader.reload()

        return {
            "success": True,
            "name": clean_name,
            "path": str(file_path),
            "total_skills": total_skills,
            "message": f"Successfully synthesized and registered skill '{clean_name}'.",
        }
    except Exception as exc:
        logger.error("Failed to save learned skill '%s': %s", clean_name, exc, exc_info=True)
        return {
            "success": False,
            "name": clean_name,
            "error": f"Failed to save skill to disk: {exc}",
        }
