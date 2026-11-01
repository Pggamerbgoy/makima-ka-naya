import time
from pathlib import Path
from typing import Dict, Any, List, Optional

class SagaRollbackManager:
    """Manages pre-state backup snapshots before destructive file writes or deletions."""
    def __init__(self, backup_dir: Path = Path.home() / ".makima" / "saga"):
        self.backup_dir = backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.ledger: List[Dict[str, Any]] = []

    def create_snapshot(self, target_path: Path, tool_name: str) -> str:
        snapshot_id = f"snap_{int(time.time() * 1000)}"
        prev_content = target_path.read_text(encoding="utf-8") if target_path.exists() else None
        
        backup_file = self.backup_dir / f"{snapshot_id}.bak"
        if prev_content is not None:
            backup_file.write_text(prev_content, encoding="utf-8")

        self.ledger.append({
            "id": snapshot_id,
            "target": str(target_path),
            "tool": tool_name,
            "timestamp": time.time(),
            "has_backup": prev_content is not None,
            "rolled_back": False,
        })
        return snapshot_id

    def rollback(self, snapshot_id: str) -> bool:
        for entry in self.ledger:
            if entry["id"] == snapshot_id and not entry["rolled_back"]:
                target = Path(entry["target"])
                backup_file = self.backup_dir / f"{snapshot_id}.bak"
                if backup_file.exists():
                    target.write_text(backup_file.read_text(encoding="utf-8"), encoding="utf-8")
                elif target.exists():
                    target.unlink()
                entry["rolled_back"] = True
                return True
        return False
