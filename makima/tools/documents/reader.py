"""
Makima v2 — Universal Document Ingestion Engine via MarkItDown.
Architectural Pattern: Hermes-style universal document reader with multi-tier fallback.
Zero-Hardcoding Guarantee: Fully dynamic path resolution via Makima filesystem boundary resolver.
Library-first: Microsoft MarkItDown for primary ingestion with graceful fallbacks
to pdfplumber (PDF), python-docx (DOCX), openpyxl (XLSX), python-pptx (PPTX), and csv.
"""

from __future__ import annotations

import csv
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from makima.tools.filesystem.safe_io import (
    BoundaryTraversalError,
    get_workspace_dir,
)
from makima.tools.registry import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path Boundary & Security Clamping
# ---------------------------------------------------------------------------

def resolve_document_path(file_path: str | Path) -> Path:
    """
    Resolves the target document path against permitted boundary roots:
      1. Dynamic workspace directory (get_workspace_dir()).
      2. User profile directory and standard user folders (Documents, Downloads, Desktop, etc.).
      3. System temporary directory (for test sandbox / generated documents).

    Args:
        file_path: Target relative or absolute file path.

    Returns:
        Canonical resolved Path if inside permitted boundaries.

    Raises:
        BoundaryTraversalError: If path escapes all permitted boundaries.
    """
    ws = get_workspace_dir().resolve()
    target = Path(file_path).expanduser()

    if target.is_absolute():
        resolved = target.resolve()
    else:
        resolved = (ws / target).resolve()

    allowed_roots: list[Path] = [ws]

    # Safe user folders (never allow the raw user home root to prevent reading .ssh, .aws, etc.)
    home = Path.home().resolve()
    for sub in ["Documents", "Downloads", "Desktop", "Music", "Videos", "Pictures", "OneDrive"]:
        sub_folder = (home / sub).resolve()
        if sub_folder.exists():
            allowed_roots.append(sub_folder)

    # Temp directory for sandboxes & tests
    temp_dir = Path(tempfile.gettempdir()).resolve()
    allowed_roots.append(temp_dir)

    # Enforce strict credential protection
    from makima.tools.filesystem.safe_io import PROTECTED_CREDENTIAL_PATTERNS
    name = resolved.name
    for pattern in PROTECTED_CREDENTIAL_PATTERNS:
        if pattern.match(name):
            raise BoundaryTraversalError(
                f"Security Violation: Access denied to protected credential/sensitive file '{name}'."
            )

    is_safe = False
    for root in allowed_roots:
        try:
            if resolved == root or resolved.is_relative_to(root):
                is_safe = True
                break
        except (ValueError, TypeError):
            continue

    if not is_safe:
        raise BoundaryTraversalError(
            f"Security Boundary Violation: Document path '{file_path}' resolves to '{resolved}', "
            f"which escapes permitted workspace boundary '{ws}' and safe user directories."
        )

    return resolved


# ---------------------------------------------------------------------------
# Specialized Fallback Ingestion Engines
# ---------------------------------------------------------------------------

def _fallback_pdf(path: Path) -> str:
    """Extracts text and formatted Markdown tables from PDF using pdfplumber, with pypdf fallback."""
    # 1. Try pdfplumber
    try:
        import pdfplumber
        chunks: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text and text.strip():
                    chunks.append(text.strip())
                tables = page.extract_tables()
                for table in tables:
                    if table and any(row for row in table):
                        headers = [str(c or "").strip() for c in table[0]]
                        chunks.append("\n| " + " | ".join(headers) + " |")
                        chunks.append("| " + " | ".join(["---"] * max(1, len(headers))) + " |")
                        for row in table[1:]:
                            chunks.append("| " + " | ".join(str(c or "").strip() for c in row) + " |")
                page.close()
        res = "\n\n".join(chunks).strip()
        if res:
            return res
    except Exception as exc:  # noqa: BLE001
        logger.debug("pdfplumber fallback failed on '%s': %s", path.name, exc)

    # 2. Try pypdf
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        text_parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t and t.strip():
                text_parts.append(t.strip())
        res = "\n\n".join(text_parts).strip()
        if res:
            return res
    except Exception as exc:  # noqa: BLE001
        logger.debug("pypdf fallback failed on '%s': %s", path.name, exc)

    return ""


def _fallback_docx(path: Path) -> str:
    """Extracts headings, paragraphs, bullet lists, and tables from Word (.docx) using python-docx."""
    try:
        import docx
        doc = docx.Document(str(path))
        lines: list[str] = []

        for p in doc.paragraphs:
            txt = p.text.strip()
            if not txt:
                continue
            style_name = p.style.name if p.style else "Normal"
            if style_name == "Title":
                lines.append(f"# {txt}\n")
            elif style_name.startswith("Heading 1"):
                lines.append(f"## {txt}\n")
            elif style_name.startswith("Heading 2"):
                lines.append(f"### {txt}\n")
            elif style_name.startswith("Heading 3"):
                lines.append(f"#### {txt}\n")
            elif "Bullet" in style_name:
                lines.append(f"- {txt}")
            else:
                lines.append(f"{txt}\n")

        for table in doc.tables:
            if not table.rows:
                continue
            headers = [cell.text.strip() for cell in table.rows[0].cells]
            lines.append("\n| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * max(1, len(headers))) + " |")
            for row in table.rows[1:]:
                lines.append("| " + " | ".join(cell.text.strip() for cell in row.cells) + " |")
            lines.append("")

        return "\n".join(lines).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("python-docx extraction failed on '%s': %s", path.name, exc)
        return ""


def _fallback_xlsx(path: Path) -> str:
    """Extracts sheets and formatted Markdown tables from Excel (.xlsx) using openpyxl."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True)
        lines: list[str] = []

        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                continue
            lines.append(f"## {sheet_name}\n")
            headers = [str(c if c is not None else "").strip() for c in rows[0]]
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * max(1, len(headers))) + " |")
            for r in rows[1:]:
                if all(v is None for v in r):
                    continue
                lines.append("| " + " | ".join(str(c if c is not None else "").strip() for c in r) + " |")
            lines.append("")

        return "\n".join(lines).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("openpyxl extraction failed on '%s': %s", path.name, exc)
        return ""


def _fallback_pptx(path: Path) -> str:
    """Extracts slide headers and content from PowerPoint (.pptx) using python-pptx."""
    try:
        from pptx import Presentation
        prs = Presentation(str(path))
        lines: list[str] = []

        for idx, slide in enumerate(prs.slides, 1):
            lines.append(f"<!-- Slide number: {idx} -->")
            if slide.shapes.title and slide.shapes.title.text.strip():
                lines.append(f"# {slide.shapes.title.text.strip()}")
            for shape in slide.shapes:
                if shape == slide.shapes.title:
                    continue
                if shape.has_text_frame:
                    for p in shape.text_frame.paragraphs:
                        txt = p.text.strip()
                        if txt:
                            lines.append(txt)
            lines.append("")

        return "\n".join(lines).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("python-pptx extraction failed on '%s': %s", path.name, exc)
        return ""


def _fallback_csv(path: Path) -> str:
    """Extracts rows from CSV file into a formatted Markdown table."""
    try:
        lines: list[str] = []
        with open(str(path), "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            rows = [row for row in reader if any(cell.strip() for cell in row)]
            if not rows:
                return ""
            headers = [c.strip() for c in rows[0]]
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * max(1, len(headers))) + " |")
            for r in rows[1:]:
                lines.append("| " + " | ".join(c.strip() for c in r) + " |")
        return "\n".join(lines).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("csv extraction failed on '%s': %s", path.name, exc)
        return ""


def _fallback_html(path: Path) -> str:
    """Extracts clean Markdown from HTML content."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        try:
            import markdownify
            return markdownify.markdownify(content, heading_style="ATX").strip()
        except ImportError:
            clean = re.sub(r"<[^>]+>", " ", content)
            return re.sub(r"\s+", " ", clean).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("html extraction failed on '%s': %s", path.name, exc)
        return ""


def _fallback_text(path: Path) -> str:
    """Extracts raw text from plain text and source files."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("text extraction failed on '%s': %s", path.name, exc)
        return ""


# ---------------------------------------------------------------------------
# Registered Universal Document Reader Tool
# ---------------------------------------------------------------------------

@tool(
    name="read_document",
    description="Converts documents (PDF, DOCX, XLSX, PPTX, CSV, HTML, TXT) directly into clean structured Markdown using MarkItDown with robust specialized fallback engines.",
    tags=["documents", "reader", "markdown", "ingest"],
)
def read_document(file_path: str, max_chars: int = 15000) -> dict[str, Any]:
    """
    Ingests and converts documents of multiple formats into clean, structured Markdown.
    Supports PDF, DOCX, XLSX, PPTX, CSV, HTML, and plain text formats.
    Clamps paths strictly within the workspace directory or safe known user folders.

    Args:
        file_path: Target document path (relative to workspace or within safe user directories).
        max_chars: Maximum character limit for extracted Markdown output (defaults to 15,000).

    Returns:
        Dictionary containing:
        - status: 'success'
        - file_path: resolved relative or clean path
        - file_name: base name of the document
        - format: file extension (e.g. '.pdf')
        - markdown: structured Markdown extracted from document
        - char_count: length of returned markdown text
        - total_chars: total length before max_chars clamp
        - truncated: bool indicating if content was truncated
        - converter: 'markitdown' or fallback engine used
        - title: optional document title if discovered

    Raises:
        BoundaryTraversalError: If path resolves outside permitted boundaries.
        FileNotFoundError: If the target document does not exist.
        IsADirectoryError: If the target path is a directory.
    """
    resolved = resolve_document_path(file_path)

    if not resolved.exists():
        raise FileNotFoundError(f"Document file not found: '{file_path}' (resolved: '{resolved}')")

    if resolved.is_dir():
        raise IsADirectoryError(f"Target path is a directory, not a file: '{file_path}'")

    ext = resolved.suffix.lower()
    markdown_text = ""
    converter_used = "markitdown"
    title: str | None = None
    markitdown_failed = False

    # Tier 1: Microsoft MarkItDown ingestion
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert(str(resolved))
        if result:
            markdown_text = (result.markdown or result.text_content or "").strip()
            title = getattr(result, "title", None)
            if not markdown_text:
                markitdown_failed = True
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "MarkItDown conversion failed for '%s' (ext: %s): %s. Triggering fallback parser.",
            resolved.name,
            ext,
            exc,
        )
        markitdown_failed = True

    # Tier 2: Specialized library-first fallbacks
    if markitdown_failed or not markdown_text:
        if ext == ".pdf":
            markdown_text = _fallback_pdf(resolved)
            converter_used = "pdfplumber"
        elif ext in (".docx", ".doc"):
            markdown_text = _fallback_docx(resolved)
            converter_used = "python-docx"
        elif ext in (".xlsx", ".xls"):
            markdown_text = _fallback_xlsx(resolved)
            converter_used = "openpyxl"
        elif ext in (".pptx", ".ppt"):
            markdown_text = _fallback_pptx(resolved)
            converter_used = "python-pptx"
        elif ext == ".csv":
            markdown_text = _fallback_csv(resolved)
            converter_used = "csv"
        elif ext in (".html", ".htm"):
            markdown_text = _fallback_html(resolved)
            converter_used = "html"
        else:
            markdown_text = _fallback_text(resolved)
            converter_used = "text"

    # Truncation and metadata formatting
    total_chars = len(markdown_text)
    if max_chars > 0 and total_chars > max_chars:
        markdown_result = markdown_text[:max_chars]
        truncated = True
    else:
        markdown_result = markdown_text
        truncated = False

    ws_root = get_workspace_dir().resolve()
    try:
        rel_path = str(resolved.relative_to(ws_root)).replace("\\", "/")
    except ValueError:
        rel_path = str(resolved).replace("\\", "/")

    return {
        "status": "success",
        "file_path": rel_path,
        "file_name": resolved.name,
        "format": ext,
        "markdown": markdown_result,
        "char_count": len(markdown_result),
        "total_chars": total_chars,
        "truncated": truncated,
        "converter": converter_used,
        "title": title,
    }
