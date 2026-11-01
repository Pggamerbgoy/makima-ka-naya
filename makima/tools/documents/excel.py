from pathlib import Path
from typing import Dict, Any, List

def generate_excel(file_path: str, headers: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
    """Generate CSV/Excel compatible spreadsheet data."""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    csv_content = ",".join(headers) + "\n" + "\n".join(",".join(map(str, r)) for r in rows)
    p.write_text(csv_content, encoding="utf-8")
    return {"path": str(p), "rows": len(rows), "status": "generated"}
