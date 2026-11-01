from pathlib import Path
from typing import Dict, Any

def generate_docx(file_path: str, title: str, content: str) -> Dict[str, Any]:
    """Generate structured document report."""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc_text = f"# {title}\n\n{content}\n"
    p.write_text(doc_text, encoding="utf-8")
    return {"path": str(p), "status": "generated"}
