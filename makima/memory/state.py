"""
Makima v2 — State Memory Engine.
Architectural Pattern: Dynamic Prompt Injection from Markdown State Files (MEMORY.md & USER.md).
Zero-Hardcoding Guarantee: Fully dynamic paths, auto-template provisioning, and thread-safe CRUD.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import List, Optional

from makima.config import get_settings, resolve_path

logger = logging.getLogger("makima.memory.state")

# -----------------------------------------------------------------------------
# Default Templates
# -----------------------------------------------------------------------------

DEFAULT_USER_TEMPLATE = """# User Profile & Persona

- **Name**: User
- **Preferred Language**: English / Hinglish
- **Communication Style**: Direct, concise, technical, no excessive pleasantries
- **Operating System**: Windows (PowerShell)
- **Primary Goals**: Autonomous AI desktop assistant development, high-leverage workflows
"""

DEFAULT_MEMORY_TEMPLATE = """# Long-Term Facts & Knowledge Base

### Architecture & System
- Assistant Persona: Yukino Yukinoshita (雪ノ下 雪乃) from Oregairu — Service Club President, composed, razor-sharp, perfectionist.
- Initialized Makima v2 Dual-Tier Memory Engine.
- Free-tier model routing and dynamic zero-cost architecture enabled.
- System operates under dynamic path resolution with zero hardcoded OS paths.
"""


# -----------------------------------------------------------------------------
# StateMemory Manager
# -----------------------------------------------------------------------------

class StateMemory:
    """
    Manages long-term static facts, user preferences, and profile context
    stored in human-readable, git-friendly Markdown files (~/.makima/MEMORY.md and USER.md).
    Dynamically injects these files into LLM system prompts on every execution turn.
    """

    def __init__(
        self,
        data_dir: Optional[Path | str] = None,
        memory_path: Optional[Path | str] = None,
        user_path: Optional[Path | str] = None,
    ) -> None:
        """
        Initialize StateMemory with dynamic path resolution.

        Args:
            data_dir: Optional directory containing MEMORY.md and USER.md. Defaults to ~/.makima.
            memory_path: Optional explicit path to MEMORY.md.
            user_path: Optional explicit path to USER.md.
        """
        if data_dir is not None:
            resolved_data = resolve_path(data_dir)
        else:
            try:
                resolved_data = get_settings().data_dir_path
            except Exception:
                resolved_data = Path.home() / ".makima"

        self.data_dir: Path = resolved_data
        self.memory_path: Path = (
            resolve_path(memory_path) if memory_path else (self.data_dir / "MEMORY.md")
        )
        self.user_path: Path = (
            resolve_path(user_path) if user_path else (self.data_dir / "USER.md")
        )

        self._lock = threading.Lock()
        self._user_cache: Optional[str] = None
        self._user_mtime_ns: Optional[int] = None
        self._memory_cache: Optional[str] = None
        self._memory_mtime_ns: Optional[int] = None
        self.ensure_files()

    def ensure_files(self) -> None:
        """
        Ensures parent directories exist and writes default Markdown templates
        if MEMORY.md or USER.md do not already exist on disk.
        """
        with self._lock:
            self.memory_path.parent.mkdir(parents=True, exist_ok=True)
            self.user_path.parent.mkdir(parents=True, exist_ok=True)

            if not self.user_path.is_file():
                logger.info(f"Creating default user profile template at {self.user_path}")
                self.user_path.write_text(DEFAULT_USER_TEMPLATE, encoding="utf-8")
                self._user_cache = None
                self._user_mtime_ns = None

            if not self.memory_path.is_file():
                logger.info(f"Creating default long-term memory template at {self.memory_path}")
                self.memory_path.write_text(DEFAULT_MEMORY_TEMPLATE, encoding="utf-8")
                self._memory_cache = None
                self._memory_mtime_ns = None

    def read_user_profile(self) -> str:
        """Reads and returns the raw content of USER.md (cached in RAM by mtime_ns)."""
        with self._lock:
            try:
                st = self.user_path.stat()
                if self._user_cache is not None and self._user_mtime_ns == st.st_mtime_ns:
                    return self._user_cache
                content = self.user_path.read_text(encoding="utf-8").strip()
                self._user_cache = content
                self._user_mtime_ns = st.st_mtime_ns
                return content
            except FileNotFoundError:
                pass
        self.ensure_files()
        with self._lock:
            st = self.user_path.stat()
            content = self.user_path.read_text(encoding="utf-8").strip()
            self._user_cache = content
            self._user_mtime_ns = st.st_mtime_ns
            return content

    def read_memory_facts(self) -> str:
        """Reads and returns the raw content of MEMORY.md (cached in RAM by mtime_ns)."""
        with self._lock:
            try:
                st = self.memory_path.stat()
                if self._memory_cache is not None and self._memory_mtime_ns == st.st_mtime_ns:
                    return self._memory_cache
                content = self.memory_path.read_text(encoding="utf-8").strip()
                self._memory_cache = content
                self._memory_mtime_ns = st.st_mtime_ns
                return content
            except FileNotFoundError:
                pass
        self.ensure_files()
        with self._lock:
            st = self.memory_path.stat()
            content = self.memory_path.read_text(encoding="utf-8").strip()
            self._memory_cache = content
            self._memory_mtime_ns = st.st_mtime_ns
            return content

    def format_prompt_injection(self, tag_format: bool = False) -> str:
        """
        Formats user profile and memory facts into a clean block suitable for system prompt injection.

        Args:
            tag_format: If True, wraps in XML tags (<user_profile> and <memory_facts>)
                        for strict LLM context isolation. If False, formats as Markdown.
        """
        user_content = self.read_user_profile()
        memory_content = self.read_memory_facts()

        if tag_format:
            parts = []
            if user_content:
                parts.append(f"<user_profile>\n{user_content}\n</user_profile>")
            if memory_content:
                parts.append(f"<memory_facts>\n{memory_content}\n</memory_facts>")
            return "\n\n".join(parts)

        sections = []
        if user_content:
            sections.append(user_content)
        if memory_content:
            sections.append(memory_content)

        return "\n\n---\n\n".join(sections)

    def append_fact(self, fact: str, category: Optional[str] = None) -> None:
        """
        Appends a new fact cleanly to MEMORY.md.

        Args:
            fact: The statement or preference to record (e.g. "User prefers pytest over unittest").
            category: Optional section heading under which to file the fact (e.g. "Preferences").
        """
        self.ensure_files()
        cleaned_fact = fact.strip()
        if not (cleaned_fact.startswith("- ") or cleaned_fact.startswith("* ")):
            cleaned_fact = f"- {cleaned_fact}"

        with self._lock:
            content = self.memory_path.read_text(encoding="utf-8")

            if category:
                category_header = f"### {category.strip()}"
                if category_header in content:
                    # Append under existing category header
                    idx = content.find(category_header) + len(category_header)
                    # Find end of category line
                    newline_idx = content.find("\n", idx)
                    if newline_idx != -1:
                        content = (
                            content[: newline_idx + 1]
                            + f"{cleaned_fact}\n"
                            + content[newline_idx + 1 :]
                        )
                    else:
                        content = content + f"\n{cleaned_fact}\n"
                else:
                    # Append new category section at the end
                    content = content.rstrip() + f"\n\n{category_header}\n{cleaned_fact}\n"
            else:
                # Append to bottom of file
                content = content.rstrip() + f"\n{cleaned_fact}\n"

            self.memory_path.write_text(content, encoding="utf-8")
            self._memory_cache = content.strip()
            self._memory_mtime_ns = self.memory_path.stat().st_mtime_ns
            logger.info(f"Recorded fact to {self.memory_path} (category: {category or 'General'})")

    def update_fact(self, search_text: str, new_fact: str) -> bool:
        """
        Finds the first fact containing search_text (case-insensitive) and replaces it with new_fact.

        Args:
            search_text: Substring to locate the existing fact.
            new_fact: Replacement statement.

        Returns:
            True if a matching line was found and replaced, False otherwise.
        """
        self.ensure_files()
        cleaned_new = new_fact.strip()
        if not (cleaned_new.startswith("- ") or cleaned_new.startswith("* ")):
            cleaned_new = f"- {cleaned_new}"

        with self._lock:
            lines = self.memory_path.read_text(encoding="utf-8").splitlines()
            found = False
            for i, line in enumerate(lines):
                if line.strip().startswith(("-", "*")) and search_text.lower() in line.lower():
                    # Preserve indentation
                    indent = len(line) - len(line.lstrip())
                    lines[i] = " " * indent + cleaned_new
                    found = True
                    break

            if found:
                new_body = "\n".join(lines) + "\n"
                self.memory_path.write_text(new_body, encoding="utf-8")
                self._memory_cache = new_body.strip()
                self._memory_mtime_ns = self.memory_path.stat().st_mtime_ns
                logger.info(f"Updated fact in {self.memory_path} matching '{search_text}'")
            return found

    def delete_fact(self, search_text: str) -> bool:
        """
        Finds the first fact containing search_text and removes it from MEMORY.md.

        Returns:
            True if a matching line was removed, False otherwise.
        """
        self.ensure_files()
        with self._lock:
            lines = self.memory_path.read_text(encoding="utf-8").splitlines()
            found = False
            new_lines = []
            for line in lines:
                if not found and line.strip().startswith(("-", "*")) and search_text.lower() in line.lower():
                    found = True
                    continue
                new_lines.append(line)

            if found:
                new_body = "\n".join(new_lines) + "\n"
                self.memory_path.write_text(new_body, encoding="utf-8")
                self._memory_cache = new_body.strip()
                self._memory_mtime_ns = self.memory_path.stat().st_mtime_ns
                logger.info(f"Deleted fact in {self.memory_path} matching '{search_text}'")
            return found

    def update_user_profile(self, new_content: str) -> None:
        """Replaces the entire content of USER.md with new_content."""
        self.ensure_files()
        with self._lock:
            new_body = new_content.strip() + "\n"
            self.user_path.write_text(new_body, encoding="utf-8")
            self._user_cache = new_body.strip()
            self._user_mtime_ns = self.user_path.stat().st_mtime_ns
            logger.info(f"Overwrote user profile at {self.user_path}")

    def append_user_profile(self, note: str) -> None:
        """Appends a preference or note bullet point to USER.md."""
        self.ensure_files()
        cleaned = note.strip()
        if not (cleaned.startswith("- ") or cleaned.startswith("* ")):
            cleaned = f"- {cleaned}"

        with self._lock:
            content = self.user_path.read_text(encoding="utf-8").rstrip()
            content = content + f"\n{cleaned}\n"
            self.user_path.write_text(content, encoding="utf-8")
            self._user_cache = content.strip()
            self._user_mtime_ns = self.user_path.stat().st_mtime_ns
            logger.info(f"Appended note to user profile at {self.user_path}")

    def delete_user_preference(self, search_text: str) -> bool:
        """
        Finds the first preference containing search_text (case-insensitive) and removes it from USER.md.

        Returns:
            True if a matching line was removed, False otherwise.
        """
        self.ensure_files()
        with self._lock:
            lines = self.user_path.read_text(encoding="utf-8").splitlines()
            found = False
            new_lines = []
            for line in lines:
                if not found and line.strip().startswith(("-", "*")) and search_text.lower() in line.lower():
                    found = True
                    continue
                new_lines.append(line)

            if found:
                new_body = "\n".join(new_lines) + "\n"
                self.user_path.write_text(new_body, encoding="utf-8")
                self._user_cache = new_body.strip()
                self._user_mtime_ns = self.user_path.stat().st_mtime_ns
                logger.info(f"Deleted preference in {self.user_path} matching '{search_text}'")
            return found

    def get_facts_list(self) -> List[str]:
        """
        Parses all bulleted points from MEMORY.md into a clean list of strings.
        """
        content = self.read_memory_facts()
        facts: List[str] = []
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("- ") or s.startswith("* "):
                cleaned = re.sub(r"^[-*]\s+", "", s)
                if cleaned:
                    facts.append(cleaned)
        return facts
