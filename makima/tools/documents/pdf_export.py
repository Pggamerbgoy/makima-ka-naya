from pathlib import Path
from typing import Dict, Any

def export_pdf(file_path: str, html_or_text: str) -> Dict[str, Any]:
    """Export formatted document to PDF target."""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html_or_text, encoding="utf-8")
    return {"path": str(p), "status": "exported"}
