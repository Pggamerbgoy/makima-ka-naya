from pathlib import Path
from typing import Dict, Any, List
import yaml

class SkillLoader:
    """Discovers and parses Markdown skills from ~/.makima/skills/ dynamically without restarts."""
    def __init__(self, skills_dir: Path = Path.home() / ".makima" / "skills"):
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.reload()

    def reload(self):
        self.skills.clear()
        for md_file in self.skills_dir.glob("**/*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        meta = yaml.safe_load(parts[1]) or {}
                        body = parts[2].strip()
                        name = meta.get("name", md_file.stem)
                        self.skills[name] = {
                            "name": name,
                            "description": meta.get("description", ""),
                            "content": body,
                            "path": str(md_file),
                        }
            except Exception:
                continue

    def list_skills(self) -> List[Dict[str, Any]]:
        return list(self.skills.values())
