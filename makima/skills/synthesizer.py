from pathlib import Path
from typing import Dict, Any

class SkillSynthesizer:
    """Synthesizes new Markdown skills from successful multi-step agent trajectories."""
    def __init__(self, skills_dir: Path = Path.home() / ".makima" / "skills"):
        self.skills_dir = skills_dir

    def synthesize(self, skill_name: str, description: str, steps_markdown: str) -> str:
        target = self.skills_dir / f"{skill_name}.md"
        content = f"---\nname: {skill_name}\ndescription: {description}\n---\n\n{steps_markdown}\n"
        target.write_text(content, encoding="utf-8")
        return str(target)
