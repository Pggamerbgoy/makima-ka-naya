import os
from pathlib import Path
from typing import Dict, Any, List

PROTECTED_CREDENTIAL_PATTERNS = [".env", "id_rsa", "wallet.dat", "credentials.json"]

class SafeFilesystem:
    """Safe Filesystem handler clamped to allowed workspace boundaries."""
    def __init__(self, workspace_root: Path = Path.cwd()):
        self.workspace_root = workspace_root.resolve()

    def _resolve(self, relative_path: str) -> Path:
        resolved = (self.workspace_root / relative_path).resolve()
        if not str(resolved).startswith(str(self.workspace_root)):
            raise PermissionError(f"Access denied: Path '{relative_path}' traverses outside workspace root.")
        return resolved

    def read_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.exists():
            raise FileNotFoundError(f"File '{path}' does not exist.")
        return p.read_text(encoding="utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": str(p), "bytes": len(content), "status": "written"}

    def list_dir(self, path: str = ".") -> List[Dict[str, Any]]:
        p = self._resolve(path)
        items = []
        for item in p.iterdir():
            items.append({
                "name": item.name,
                "is_dir": item.is_dir(),
                "size": item.stat().st_size if item.is_file() else 0,
            })
        return items
