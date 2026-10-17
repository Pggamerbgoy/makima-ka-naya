"""
Makima v2 — Document Processing Toolset.
Architectural Pattern: Hermes-style modular document tools with workspace boundary clamping.
Zero-Hardcoding Guarantee: Fully dynamic path resolution via Makima filesystem boundary resolver.
Library-first: Direct use of openpyxl, python-docx, and python-pptx.
"""

from __future__ import annotations

from makima.tools.documents.excel import create_excel_sheet, read_excel_sheet
from makima.tools.documents.presentation import create_powerpoint, read_powerpoint
from makima.tools.documents.reader import read_document
from makima.tools.documents.word import create_word_document, read_word_document

__all__ = [
    # Universal Document Reader
    "read_document",
    # Excel Tools
    "create_excel_sheet",
    "read_excel_sheet",
    # Word Tools
    "create_word_document",
    "read_word_document",
    # PowerPoint Tools
    "create_powerpoint",
    "read_powerpoint",
]
