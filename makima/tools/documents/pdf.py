"""
Makima v2 — Document Processing: Native Headless PDF Engine.
Architectural Pattern: Hermes-style modular document tools with workspace boundary clamping.
Zero-Hardcoding Guarantee: Fully dynamic path resolution via Makima filesystem boundary resolver.
Library-first: ReportLab with zero Microsoft Office / COM / external printer dependencies.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import docx
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from makima.tools.filesystem.safe_io import resolve_safe_path
from makima.tools.registry import tool

logger = logging.getLogger(__name__)


def _build_pdf_styles() -> Dict[str, ParagraphStyle]:
    base_styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DocTitle",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=14,
        ),
        "h1": ParagraphStyle(
            "Heading1",
            parent=base_styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#1e40af"),
            spaceBefore=14,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "Heading2",
            parent=base_styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#0369a1"),
            spaceBefore=10,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "Heading3",
            parent=base_styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#0284c7"),
            spaceBefore=8,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14.5,
            textColor=colors.HexColor("#334155"),
            spaceAfter=8,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#334155"),
            leftIndent=16,
            firstLineIndent=-10,
            spaceAfter=4,
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#1e293b"),
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=colors.white,
        ),
    }


# ---------------------------------------------------------------------------
# Registered Tools
# ---------------------------------------------------------------------------

@tool(
    name="create_pdf_document",
    description="Creates a professional, publication-grade PDF document (.pdf) with headings, formatted paragraphs, bullet lists, and styled data tables without requiring Microsoft Word or Office.",
    tags=["documents", "pdf", "export"],
)
def create_pdf_document(
    file_path: str,
    title: str,
    sections: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Creates a styled PDF document populated with structured sections.

    Args:
        file_path: Destination path relative to the workspace boundary (e.g. 'reports/summary.pdf').
        title: Document title displayed prominently at the top.
        sections: List of section dicts. Each section can contain:
                  - 'heading': Section title string.
                  - 'level': Heading depth (1 to 4, defaults to 1).
                  - 'text': Main paragraph text string.
                  - 'paragraphs': Optional list of multiple text paragraph strings.
                  - 'bullets': Optional list of bullet point strings.
                  - 'table': Optional dict with 'headers' (list[str]) and 'rows' (list[list[Any]]).

    Returns:
        Dictionary containing document creation status, file metadata, and page counts.
    """
    if not title:
        raise ValueError("Cannot create PDF document with an empty title.")

    resolved = resolve_safe_path(file_path)
    if resolved.suffix.lower() != ".pdf":
        resolved = resolved.with_suffix(".pdf")

    resolved.parent.mkdir(parents=True, exist_ok=True)

    styles = _build_pdf_styles()
    story = [
        Paragraph(title, styles["title"]),
        HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#3b82f6"), spaceAfter=14),
    ]

    total_paragraphs = 0
    total_tables = 0
    total_bullets = 0

    for section in sections:
        heading = section.get("heading")
        level = int(section.get("level", 1))
        if heading:
            style_key = "h1" if level == 1 else "h2" if level == 2 else "h3"
            story.append(Paragraph(str(heading), styles[style_key]))

        text = section.get("text")
        if text:
            story.append(Paragraph(str(text), styles["body"]))
            total_paragraphs += 1

        paragraphs = section.get("paragraphs", [])
        for p in paragraphs:
            if p:
                story.append(Paragraph(str(p), styles["body"]))
                total_paragraphs += 1

        bullets = section.get("bullets", [])
        for b in bullets:
            if b:
                story.append(Paragraph(f"&bull;&nbsp;&nbsp;{b}", styles["bullet"]))
                total_bullets += 1

        table_data = section.get("table")
        if isinstance(table_data, dict):
            headers = table_data.get("headers", [])
            rows = table_data.get("rows", [])
            if headers or rows:
                formatted_data = []
                if headers:
                    formatted_data.append([Paragraph(str(h), styles["table_header"]) for h in headers])
                for row in rows:
                    formatted_data.append([Paragraph(str(c), styles["table_cell"]) for c in row])

                col_count = max(len(r) for r in formatted_data)
                # Compute available printable width (letter = 612, margins = 54 + 54 = 108 -> 504 pt)
                col_width = 504.0 / col_count if col_count > 0 else 100.0

                tbl = Table(formatted_data, colWidths=[col_width] * col_count)
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ]))
                story.append(Spacer(1, 4))
                story.append(tbl)
                story.append(Spacer(1, 8))
                total_tables += 1

    doc = SimpleDocTemplate(
        str(resolved),
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=54,
    )
    doc.build(story)

    size_bytes = resolved.stat().st_size
    return {
        "status": "created",
        "file_path": str(resolved),
        "file_name": resolved.name,
        "size_bytes": size_bytes,
        "sections_count": len(sections),
        "paragraphs_count": total_paragraphs,
        "bullets_count": total_bullets,
        "tables_count": total_tables,
    }


@tool(
    name="convert_docx_to_pdf",
    description="Converts an existing Word document (.docx) into a high-quality PDF (.pdf) natively and headlessly without requiring Microsoft Word or Office.",
    tags=["documents", "pdf", "word", "conversion"],
)
def convert_docx_to_pdf(
    docx_path: str,
    pdf_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Converts a .docx document into a clean PDF using native ReportLab flowables.

    Args:
        docx_path: Source path to the .docx document.
        pdf_path: Optional destination .pdf path. If omitted, uses the same base name with .pdf extension.

    Returns:
        Dictionary containing conversion status, paths, and size.
    """
    resolved_in = resolve_safe_path(docx_path)
    if not resolved_in.exists():
        raise FileNotFoundError(f"Source Word document not found at '{resolved_in}'")

    if pdf_path:
        resolved_out = resolve_safe_path(pdf_path)
    else:
        resolved_out = resolved_in.with_suffix(".pdf")

    resolved_out.parent.mkdir(parents=True, exist_ok=True)

    doc_in = docx.Document(str(resolved_in))
    styles = _build_pdf_styles()

    story = []
    seen_title = False

    for p in doc_in.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style_name = p.style.name.lower()
        if "title" in style_name:
            story.append(Paragraph(text, styles["title"]))
            story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#3b82f6"), spaceAfter=14))
            seen_title = True
        elif "heading 1" in style_name:
            story.append(Paragraph(text, styles["h1"]))
        elif "heading 2" in style_name:
            story.append(Paragraph(text, styles["h2"]))
        elif "heading" in style_name:
            story.append(Paragraph(text, styles["h3"]))
        elif "list bullet" in style_name or text.startswith("- ") or text.startswith("• "):
            clean_b = text.lstrip("-•* ").strip()
            story.append(Paragraph(f"&bull;&nbsp;&nbsp;{clean_b}", styles["bullet"]))
        else:
            if not seen_title:
                # If first paragraph was plain text but formatted as title
                story.append(Paragraph(text, styles["title"]))
                story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#3b82f6"), spaceAfter=14))
                seen_title = True
            else:
                story.append(Paragraph(text, styles["body"]))

    # Convert any tables in the docx
    for t in doc_in.tables:
        table_data = []
        for row_idx, r in enumerate(t.rows):
            row_cells = []
            for c in r.cells:
                txt = c.text.strip()
                cell_style = styles["table_header"] if row_idx == 0 else styles["table_cell"]
                row_cells.append(Paragraph(txt, cell_style))
            table_data.append(row_cells)

        if table_data:
            col_count = max(len(r) for r in table_data)
            col_width = 504.0 / col_count if col_count > 0 else 100.0
            tbl = Table(table_data, colWidths=[col_width] * col_count)
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ]))
            story.append(Spacer(1, 6))
            story.append(tbl)
            story.append(Spacer(1, 8))

    pdf = SimpleDocTemplate(
        str(resolved_out),
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=54,
    )
    pdf.build(story)

    return {
        "status": "converted",
        "source_docx": str(resolved_in),
        "target_pdf": str(resolved_out),
        "size_bytes": resolved_out.stat().st_size,
    }
