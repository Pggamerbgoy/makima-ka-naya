"""
Live verification script for Step 28: Universal Document Ingestion via MarkItDown.
Tests:
  1. CSV document ingestion to clean Markdown table.
  2. TXT document ingestion to clean Markdown text.
  3. Word (.docx) document ingestion to structured Markdown.
  4. PDF (.pdf) document ingestion to clean Markdown.
  5. Excel (.xlsx) document ingestion to structured Markdown.
  6. HTML (.html) document ingestion to clean Markdown.
  7. max_chars truncation behavior and char counting.
  8. Boundary traversal and security clamping.
  9. ToolRegistry auto-discovery and dynamic execution.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.tools import get_registry, reset_registry
from makima.tools.documents import read_document
from makima.tools.filesystem.safe_io import (
    BoundaryTraversalError,
    set_workspace_dir,
)


def test_csv_ingestion(tmp_dir: Path):
    print("\n[TEST 1] Testing CSV document ingestion via read_document...")
    csv_path = tmp_dir / "data" / "employees.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(
        "Name,Role,Department\nAlice,AI Engineer,Core\nBob,Security Architect,Infra\n",
        encoding="utf-8",
    )

    res = read_document(str(csv_path))
    assert res["status"] == "success", f"CSV ingestion failed: {res}"
    assert res["format"] == ".csv"
    assert "Alice" in res["markdown"]
    assert "Role" in res["markdown"]
    assert "|" in res["markdown"]  # Structured table
    assert res["truncated"] is False
    assert res["char_count"] > 0
    print(f"  [PASS] CSV converted cleanly to Markdown ({res['char_count']} chars, converter: {res['converter']}).")


def test_txt_ingestion(tmp_dir: Path):
    print("\n[TEST 2] Testing plain TXT document ingestion...")
    txt_path = tmp_dir / "notes.txt"
    txt_content = "# Project Notes\nThis is a test of MarkItDown universal ingestion.\n- Point 1\n- Point 2"
    txt_path.write_text(txt_content, encoding="utf-8")

    res = read_document(str(txt_path))
    assert res["status"] == "success"
    assert res["format"] == ".txt"
    assert "Project Notes" in res["markdown"]
    assert "Point 1" in res["markdown"]
    assert res["truncated"] is False
    print(f"  [PASS] TXT ingested cleanly ({res['char_count']} chars, converter: {res['converter']}).")


def test_docx_ingestion(tmp_dir: Path):
    print("\n[TEST 3] Testing Word (.docx) document ingestion...")
    import docx

    doc_path = tmp_dir / "specification.docx"
    doc = docx.Document()
    doc.add_heading("Architecture Specification", level=1)
    doc.add_paragraph("Makima v2 incorporates Hermes-style tool patterns.")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Component"
    table.rows[0].cells[1].text = "Status"
    table.rows[1].cells[0].text = "MarkItDown"
    table.rows[1].cells[1].text = "Active"
    doc.save(str(doc_path))

    res = read_document(str(doc_path))
    assert res["status"] == "success"
    assert res["format"] == ".docx"
    assert "Architecture Specification" in res["markdown"]
    assert "MarkItDown" in res["markdown"]
    assert res["char_count"] > 0
    print(f"  [PASS] DOCX converted to Markdown ({res['char_count']} chars, converter: {res['converter']}).")


def test_pdf_ingestion(tmp_dir: Path):
    print("\n[TEST 4] Testing PDF (.pdf) document ingestion...")
    pdf_path = tmp_dir / "whitepaper.pdf"

    # Minimal valid single-page PDF with text stream
    pdf_bytes = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 55 >>
stream
BT
/F1 18 Tf
0 50 Td
(Hello from Universal Document Ingestion!) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000228 00000 n 
0000000333 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
412
%%EOF"""
    pdf_path.write_bytes(pdf_bytes)

    res = read_document(str(pdf_path))
    assert res["status"] == "success"
    assert res["format"] == ".pdf"
    assert "Universal Document Ingestion" in res["markdown"]
    assert res["char_count"] > 0
    print(f"  [PASS] PDF converted to Markdown ({res['char_count']} chars, converter: {res['converter']}).")


def test_xlsx_ingestion(tmp_dir: Path):
    print("\n[TEST 5] Testing Excel (.xlsx) document ingestion...")
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Financials"
    ws.append(["Quarter", "Revenue", "Margin"])
    ws.append(["Q1 2026", "$150,000", "42%"])
    ws.append(["Q2 2026", "$210,000", "48%"])

    xlsx_path = tmp_dir / "financials.xlsx"
    wb.save(str(xlsx_path))

    res = read_document(str(xlsx_path))
    assert res["status"] == "success"
    assert res["format"] == ".xlsx"
    assert "Financials" in res["markdown"] or "Quarter" in res["markdown"]
    assert "Revenue" in res["markdown"]
    print(f"  [PASS] XLSX converted to Markdown ({res['char_count']} chars, converter: {res['converter']}).")


def test_html_ingestion(tmp_dir: Path):
    print("\n[TEST 6] Testing HTML (.html) document ingestion...")
    html_path = tmp_dir / "index.html"
    html_path.write_text(
        "<html><body><h1>Deployment Guide</h1><p>MarkItDown parses HTML effortlessly.</p></body></html>",
        encoding="utf-8",
    )

    res = read_document(str(html_path))
    assert res["status"] == "success"
    assert res["format"] == ".html"
    assert "Deployment Guide" in res["markdown"]
    print(f"  [PASS] HTML converted to Markdown ({res['char_count']} chars, converter: {res['converter']}).")


def test_max_chars_truncation(tmp_dir: Path):
    print("\n[TEST 7] Testing max_chars truncation behavior...")
    long_path = tmp_dir / "long_document.txt"
    long_path.write_text("A" * 500, encoding="utf-8")

    res = read_document(str(long_path), max_chars=100)
    assert res["status"] == "success"
    assert res["truncated"] is True
    assert res["char_count"] == 100
    assert res["total_chars"] == 500
    assert len(res["markdown"]) == 100
    print("  [PASS] max_chars correctly truncated content and flagged truncated=True.")


def test_security_and_boundary(tmp_dir: Path):
    print("\n[TEST 8] Testing boundary traversal prevention...")
    try:
        # Attempt traversal outside workspace and safe directories
        read_document(r"C:\Windows\System32\drivers\etc\hosts")
        assert False, "Should have raised BoundaryTraversalError for C:\\Windows\\..."
    except (BoundaryTraversalError, PermissionError) as exc:
        print(f"  [PASS] Blocked external directory traversal: {type(exc).__name__}")

    try:
        read_document(str(tmp_dir / "non_existent_file.pdf"))
        assert False, "Should have raised FileNotFoundError for missing file."
    except FileNotFoundError:
        print("  [PASS] Missing file properly raised FileNotFoundError.")


async def test_tool_registry_integration(tmp_dir: Path):
    print("\n[TEST 9] Testing ToolRegistry discovery and dynamic execution...")
    reset_registry()
    reg = get_registry(auto_discover=True)

    assert reg.has("read_document"), "read_document was not discovered by ToolRegistry!"
    tool_obj = reg.get("read_document")
    assert tool_obj is not None
    assert "documents" in tool_obj.tags

    # Dynamic execution through registry
    sample_txt = tmp_dir / "dyn_doc.txt"
    sample_txt.write_text("Hello dynamic registry execution!", encoding="utf-8")

    dyn_res = await reg.execute("read_document", {"file_path": str(sample_txt)})
    assert dyn_res["status"] == "success"
    assert "Hello dynamic registry" in dyn_res["markdown"]
    print("  [PASS] read_document dynamically discovered and executed via ToolRegistry.")


async def main():
    print("=" * 75)
    print("MAKIMA v2 — STEP 28: UNIVERSAL DOCUMENT INGESTION VERIFICATION")
    print("=" * 75)

    with tempfile.TemporaryDirectory() as temp_dir_str:
        tmp_dir = Path(temp_dir_str).resolve()
        try:
            set_workspace_dir(tmp_dir)
            test_csv_ingestion(tmp_dir)
            test_txt_ingestion(tmp_dir)
            test_docx_ingestion(tmp_dir)
            test_pdf_ingestion(tmp_dir)
            test_xlsx_ingestion(tmp_dir)
            test_html_ingestion(tmp_dir)
            test_max_chars_truncation(tmp_dir)
            test_security_and_boundary(tmp_dir)
            await test_tool_registry_integration(tmp_dir)
        finally:
            set_workspace_dir(None)

    print("\n" + "=" * 75)
    print("ALL STEP 28 MARKITDOWN TESTS PASSED (EXIT CODE 0)")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
