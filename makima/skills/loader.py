"""
Makima v2 — Dynamic Markdown Skills Engine.
Architectural Pattern: Modular skills loader parsing YAML frontmatter and markdown instructions.
Rule 6: Clean, modular Makima v2 code. Zero copy-paste from v1.
Rule 7: Library-first using pathlib, yaml (pyyaml), and pydantic.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """Represents a procedural capability or operating procedure for Makima agents."""
    name: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    body: str = ""
    path: Optional[Path] = None

    def to_markdown(self) -> str:
        """Reconstructs the full markdown file with YAML frontmatter."""
        meta = {
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "version": self.version,
        }
        yaml_str = yaml.safe_dump(meta, sort_keys=False).strip()
        return f"---\n{yaml_str}\n---\n\n{self.body.strip()}\n"

    def to_prompt_entry(self) -> str:
        """Formats the skill as a markdown section for LLM system prompt injection."""
        tags_str = ", ".join(self.tags) if self.tags else "none"
        header = f"### Skill: {self.name}"
        if self.description:
            header += f"\n**Description**: {self.description}"
        header += f"\n**Tags**: {tags_str}"
        return f"{header}\n\n{self.body.strip()}"


class SkillsLoader:
    """
    Scans configured skills directories for '**/*.md' or '**/SKILL.md' files,
    parses YAML frontmatter, and provides fast search and prompt synthesis.
    """

    def __init__(
        self,
        skills_dir: Optional[Union[str, Path]] = None,
        extra_paths: Optional[List[Union[str, Path]]] = None,
    ):
        if skills_dir is not None:
            self.skills_dir = Path(skills_dir).expanduser().resolve()
        else:
            try:
                from makima.config import get_settings
                self.skills_dir = get_settings().skills_dir_path
            except Exception:
                self.skills_dir = (Path.home() / ".makima" / "skills").resolve()

        self.extra_paths: List[Path] = [
            Path(p).expanduser().resolve() for p in (extra_paths or [])
        ]
        self._cache: Dict[str, Skill] = {}
        self._loaded: bool = False

    def _parse_file(self, file_path: Path) -> Optional[Skill]:
        """Reads a markdown file, parses frontmatter and body, returning a Skill instance."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to read skill file %s: %s", file_path, exc)
            return None

        norm = content.replace("\r\n", "\n").strip()
        meta: Dict[str, Any] = {}
        body: str = ""

        # Match YAML frontmatter between leading --- delimiters
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n(.*))?$", norm, re.DOTALL)
        if frontmatter_match:
            try:
                meta = yaml.safe_load(frontmatter_match.group(1)) or {}
            except Exception as yaml_err:
                logger.warning("YAML parse error in %s: %s", file_path, yaml_err)
                meta = {}
            body = (frontmatter_match.group(2) or "").strip()
        else:
            # Fallback: check first header for name, rest as body
            body = norm
            lines = [l.strip() for l in norm.splitlines() if l.strip()]
            if lines and lines[0].startswith("# "):
                derived_name = lines[0].lstrip("# ").strip().lower().replace(" ", "_")
                meta["name"] = derived_name

        # Resolve skill name
        default_name = (
            file_path.parent.name
            if file_path.stem.upper() == "SKILL"
            else file_path.stem
        )
        name = str(meta.get("name") or default_name).strip()
        description = str(meta.get("description") or "").strip()
        tags_raw = meta.get("tags") or []
        tags = [str(t).strip() for t in tags_raw] if isinstance(tags_raw, list) else [str(tags_raw).strip()]
        version = str(meta.get("version") or "1.0.0").strip()

        return Skill(
            name=name,
            description=description,
            tags=tags,
            version=version,
            body=body,
            path=file_path,
        )

    def load_all(self, force_reload: bool = False) -> Dict[str, Skill]:
        """
        Scans all configured skill directories and loads all markdown skills.
        Caches results unless force_reload is True.
        """
        if self._loaded and not force_reload:
            return dict(self._cache)

        skills: Dict[str, Skill] = {}
        all_dirs: List[Path] = [self.skills_dir] + self.extra_paths

        for base_dir in all_dirs:
            if not base_dir.exists():
                continue

            # Find all markdown files (supports both <name>/SKILL.md and <name>.md)
            for md_file in sorted(base_dir.rglob("*.md")):
                if md_file.name.startswith("."):
                    continue
                skill = self._parse_file(md_file)
                if skill and skill.name:
                    skills[skill.name] = skill

        self._cache = skills
        self._loaded = True
        return dict(self._cache)

    def reload(self) -> int:
        """Forces a reload of all skills from disk and returns the total count."""
        skills = self.load_all(force_reload=True)
        return len(skills)

    def get_skill(self, name: str) -> Optional[Skill]:
        """Retrieves a skill by name (exact or case-insensitive)."""
        if not self._loaded:
            self.load_all()

        if name in self._cache:
            return self._cache[name]

        lower = name.lower().strip()
        for k, v in self._cache.items():
            if k.lower() == lower:
                return v
        return None

    def search_skills(self, query: str = "", tags: Optional[List[str]] = None) -> List[Skill]:
        """
        Searches skills by text query in name/description/body/tags and/or tag filter.
        """
        if not self._loaded:
            self.load_all()

        results: List[Skill] = []
        q_lower = query.lower().strip() if query else ""
        target_tags = set(t.lower().strip() for t in tags) if tags else set()

        for skill in self._cache.values():
            # Check tags
            if target_tags:
                skill_tags = set(t.lower().strip() for t in skill.tags)
                if not (target_tags & skill_tags):
                    continue

            # Check query string
            if q_lower:
                text_match = (
                    q_lower in skill.name.lower()
                    or q_lower in skill.description.lower()
                    or q_lower in skill.body.lower()
                    or any(q_lower in t.lower() for t in skill.tags)
                )
                if not text_match:
                    continue

            results.append(skill)

        return results

    def build_system_prompt_section(
        self,
        skills: Optional[List[Skill]] = None,
        max_tokens_estimate: Optional[int] = None,
    ) -> str:
        """
        Constructs an optimized system prompt section containing active skills.
        """
        if skills is None:
            if not self._loaded:
                self.load_all()
            skills = list(self._cache.values())

        if not skills:
            return ""

        entries: List[str] = []
        current_chars = 0
        max_chars = (max_tokens_estimate * 4) if max_tokens_estimate else None

        for skill in skills:
            entry = skill.to_prompt_entry()
            if max_chars is not None and (current_chars + len(entry) > max_chars):
                break
            entries.append(entry)
            current_chars += len(entry)

        if not entries:
            return ""

        header = "## Active Learned Skills\n\nThe following specialized procedural skills are loaded and available:\n\n"
        return header + "\n\n".join(entries)


# ---------------------------------------------------------------------------
# Global Loader Accessor
# ---------------------------------------------------------------------------

_GLOBAL_LOADER: Optional[SkillsLoader] = None


def get_skills_loader(
    skills_dir: Optional[Union[str, Path]] = None,
    reset: bool = False,
) -> SkillsLoader:
    """Returns or initializes the singleton SkillsLoader instance."""
    global _GLOBAL_LOADER
    if _GLOBAL_LOADER is None or reset or skills_dir is not None:
        _GLOBAL_LOADER = SkillsLoader(skills_dir=skills_dir)
    return _GLOBAL_LOADER
