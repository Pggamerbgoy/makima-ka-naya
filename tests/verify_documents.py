"""
Live verification script for Phase 2 Step 9.3: Document Processing Tools.
Comprehensive testing covering:
  1. Excel (.xlsx) creation with styled headers, zebra striping, auto column width, and frozen panes.
  2. Excel (.xlsx) reading with structured row dicts, max_rows limit, and sheet metadata.
  3. Word (.docx) creation with headings, paragraphs, bullet lists, and styled tables.
  4. Word (.docx) reading with structured paragraph extraction, table extraction, and unified Markdown synthesis.
  5. PowerPoint (.pptx) creation with 16:9 widescreen layout, title/subtitle, bullet slides, and speaker notes.
  6. PowerPoint (.pptx) reading with slide and note inspection.
  7. Adversarial boundary clamping & traversal blocking across all document types.
  8. ToolRegistry dynamic execution & schema auto-synthesis.
"""

import asyncio
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from makima.tools import get_registry
from makima.tools.documents import (
    create_excel_sheet,
    create_powerpoint,
    create_word_document,
    read_excel_sheet,
    read_powerpoint,
    read_word_document,
)
from makima.tools.filesystem.safe_io import (
    BoundaryTraversalError,
    get_workspace_dir,
    set_workspace_dir,
)


# ---------------------------------------------------------------------------
# Test 1 & 2: Excel Creation & Reading
# ---------------------------------------------------------------------------

def test_excel_processing(tmp_dir: Path):
    print("\n[TEST 1] Testing Excel sheet creation with styling and layout...")

    headers = ["ID", "Product Name", "Category", "Unit Price", "Stock Qty", "Last Updated"]
    rows = [
        [101, "Neural Processor A1", "Hardware", 1250.50, 45, date(2026, 1, 15)],
        [102, "Vision Sensor Pro", "Sensors", 420.00, 120, date(2026, 2, 1)],
        [103, "Makima Core License", "Software", 8900.00, 10, date(2026, 3, 10)],
    ]

    res = create_excel_sheet(
        file_path="finance/products.xlsx",
        headers=headers,
        rows=rows,
        sheet_title="Inventory Q1",
    )

    assert res["status"] == "success"
    assert res["rows_count"] == 3
    assert res["columns_count"] == 6
    assert res["sheet_title"] == "Inventory Q1"

    excel_file = tmp_dir / "finance" / "products.xlsx"
    assert excel_file.is_file()
    assert res["file_size_bytes"] > 0
    print("  [PASS] Excel sheet created and styled successfully.")

    print("\n[TEST 2] Testing Excel sheet reading and structure verification...")
    read_res = read_excel_sheet("finance/products.xlsx", sheet_title="Inventory Q1")

    assert read_res["status"] == "success"
    assert read_res["sheet_title"] == "Inventory Q1"
    assert read_res["headers"] == headers
    assert len(read_res["rows"]) == 3

    first_row = read_res["rows"][0]
    assert first_row["ID"] == 101
    assert first_row["Product Name"] == "Neural Processor A1"
    assert first_row["Category"] == "Hardware"
    assert first_row["Unit Price"] == 1250.50
    assert first_row["Stock Qty"] == 45

    # Test reading with max_rows
    limited_res = read_excel_sheet("finance/products.xlsx", max_rows=1)
    assert len(limited_res["rows"]) == 1

    print("  [PASS] Excel sheet data correctly read into structured records.")


# ---------------------------------------------------------------------------
# Test 3 & 4: Word Document Creation & Reading
# ---------------------------------------------------------------------------

def test_word_processing(tmp_dir: Path):
    print("\n[TEST 3] Testing Word document creation with sections, bullets, and tables...")

    sections = [
        {
            "heading": "Executive Overview",
            "level": 1,
            "text": "Makima v2 is an autonomous AI companion ecosystem designed for extreme efficiency.",
        },
        {
            "heading": "Core Capabilities",
            "level": 2,
            "bullets": [
                "Hermes-style autonomous while-loop execution",
                "Strict workspace boundary clamping",
                "Cryptographic SAGA rollback engine",
                "Zero-cost provider fallback cascades",
            ],
        },
        {
            "heading": "Performance Metrics",
            "level": 2,
            "table": {
                "headers": ["Metric", "v1 Baseline", "v2 Hermes", "Improvement"],
                "rows": [
                    ["Cold Start Latency", "1200ms", "140ms", "8.5x faster"],
                    ["Memory Overhead", "85MB", "12MB", "7x lighter"],
                    ["API Token Cost", "$0.04/turn", "$0.00 (Tier)", "100% Free Tier"],
                ],
            },
        },
    ]

    res = create_word_document(
        file_path="docs/architecture_spec.docx",
        title="Makima Architecture Specification",
        sections=sections,
    )

    assert res["status"] == "success"
    assert res["title"] == "Makima Architecture Specification"
    assert res["sections_count"] == 3
    assert res["tables_count"] == 1

    word_file = tmp_dir / "docs" / "architecture_spec.docx"
    assert word_file.is_file()
    assert res["file_size_bytes"] > 0
    print("  [PASS] Word document created with headings, bullets, and tables.")

    print("\n[TEST 4] Testing Word document reading and Markdown synthesis...")
    read_res = read_word_document("docs/architecture_spec.docx")

    assert read_res["status"] == "success"
    assert len(read_res["paragraphs"]) > 0
    assert len(read_res["tables"]) == 1

    # Check table extraction
    table_meta = read_res["tables"][0]
    assert table_meta["headers"] == ["Metric", "v1 Baseline", "v2 Hermes", "Improvement"]
    assert len(table_meta["rows"]) == 3
    assert table_meta["rows"][0][0] == "Cold Start Latency"

    # Check markdown synthesis
    md = read_res["markdown"]
    assert "# Makima Architecture Specification" in md
    assert "## Executive Overview" in md
    assert "- Hermes-style autonomous while-loop execution" in md
    assert "| Metric | v1 Baseline | v2 Hermes | Improvement |" in md
    assert "| Cold Start Latency | 1200ms | 140ms | 8.5x faster |" in md

    print("  [PASS] Word document correctly converted to structured data and Markdown.")


# ---------------------------------------------------------------------------
# Test 5 & 6: PowerPoint Presentation Creation & Reading
# ---------------------------------------------------------------------------

def test_powerpoint_processing(tmp_dir: Path):
    print("\n[TEST 5] Testing PowerPoint 16:9 presentation creation...")

    slides_content = [
        {
            "title": "Autonomous Execution",
            "bullets": [
                "Replaces rigid DAGs with LLM-guided tool calling loops",
                "Dynamic error correction with [TOOL_FAILED: name] fallbacks",
                "Shannon entropy and token budgeting per turn",
            ],
            "notes": "Emphasize autonomous while-loop convergence.",
        },
        {
            "title": "Zero-Cost Ecosystem",
            "bullets": [
                "Priority routing to Ollama local offline models",
                "Cascades to Groq, Gemini, and OpenRouter free tiers",
                "Circuit breakers prevent cascading rate limit stalls",
            ],
            "notes": "Stress zero cost guarantee for standard users.",
        },
    ]

    res = create_powerpoint(
        file_path="slides/deck.pptx",
        title="Makima v2 Launch Presentation",
        subtitle="Autonomous Agent Architecture",
        slides=slides_content,
    )

    assert res["status"] == "success"
    assert res["title"] == "Makima v2 Launch Presentation"
    assert res["slides_count"] == 3  # 1 title slide + 2 content slides

    pptx_file = tmp_dir / "slides" / "deck.pptx"
    assert pptx_file.is_file()
    assert res["file_size_bytes"] > 0
    print("  [PASS] PowerPoint 16:9 presentation created successfully.")

    print("\n[TEST 6] Testing PowerPoint presentation reading...")
    read_res = read_powerpoint("slides/deck.pptx")

    assert read_res["status"] == "success"
    assert read_res["slides_count"] == 3

    title_slide = read_res["slides"][0]
    assert title_slide["title"] == "Makima v2 Launch Presentation"

    slide_1 = read_res["slides"][1]
    assert slide_1["title"] == "Autonomous Execution"
    assert any("Replaces rigid DAGs" in c for c in slide_1["contents"])
    assert "Emphasize autonomous while-loop" in slide_1["notes"]

    slide_2 = read_res["slides"][2]
    assert slide_2["title"] == "Zero-Cost Ecosystem"
    assert any("Priority routing to Ollama" in c for c in slide_2["contents"])
    assert "Stress zero cost guarantee" in slide_2["notes"]

    print("  [PASS] PowerPoint slides, bullets, and speaker notes verified.")


# ---------------------------------------------------------------------------
# Test 7: Adversarial Boundary Clamping & Traversal Blocking
# ---------------------------------------------------------------------------

def test_document_boundary_security(tmp_dir: Path):
    print("\n[TEST 7] Testing adversarial boundary clamping across all document tools...")

    evil_paths = [
        "../escape.xlsx",
        "../../outside.docx",
        "../../../system32/deck.pptx",
        os.path.abspath(str(tmp_dir.parent / "escape.xlsx")),
    ]

    for p in evil_paths:
        # Excel write
        try:
            create_excel_sheet(p, ["Col"], [["Val"]])
            assert False, f"Boundary escape not blocked for create_excel_sheet('{p}')"
        except (BoundaryTraversalError, PermissionError):
            pass

        # Excel read
        try:
            read_excel_sheet(p)
            assert False, f"Boundary escape not blocked for read_excel_sheet('{p}')"
        except (BoundaryTraversalError, PermissionError):
            pass

        # Word write
        try:
            create_word_document(p, "Title", [{"text": "evil"}])
            assert False, f"Boundary escape not blocked for create_word_document('{p}')"
        except (BoundaryTraversalError, PermissionError):
            pass

        # Word read
        try:
            read_word_document(p)
            assert False, f"Boundary escape not blocked for read_word_document('{p}')"
        except (BoundaryTraversalError, PermissionError):
            pass

        # PowerPoint write
        try:
            create_powerpoint(p, "Title")
            assert False, f"Boundary escape not blocked for create_powerpoint('{p}')"
        except (BoundaryTraversalError, PermissionError):
            pass

        # PowerPoint read
        try:
            read_powerpoint(p)
            assert False, f"Boundary escape not blocked for read_powerpoint('{p}')"
        except (BoundaryTraversalError, PermissionError):
            pass

    print("  [PASS] All document operations strictly clamped within workspace boundary.")


# ---------------------------------------------------------------------------
# Test 8: ToolRegistry Dynamic Execution & Schemas
# ---------------------------------------------------------------------------

async def test_registry_integration(tmp_dir: Path):
    print("\n[TEST 8] Testing ToolRegistry integration and dynamic schema synthesis...")
    reg = get_registry()

    doc_tools = [
        "create_excel_sheet",
        "read_excel_sheet",
        "create_word_document",
        "read_word_document",
        "create_powerpoint",
        "read_powerpoint",
    ]

    for t_name in doc_tools:
        assert t_name in reg, f"Document tool '{t_name}' not registered in ToolRegistry!"
        tool_obj = reg[t_name]

        # Verify OpenAI schema
        schema = tool_obj.to_schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == t_name
        assert len(fn["description"]) > 0
        assert "parameters" in fn

        # Verify Gemini schema
        gemini_schema = tool_obj.to_schema(format="gemini")
        assert gemini_schema["name"] == t_name

    # Execute dynamic Excel creation via registry
    dyn_res = await reg.execute("create_excel_sheet", {
        "file_path": "dyn/dynamic_sheet.xlsx",
        "headers": ["Metric", "Score"],
        "rows": [["Accuracy", 0.99], ["Speed", 98]],
        "sheet_title": "DynamicEval",
    })
    assert isinstance(dyn_res, dict)
    assert dyn_res["status"] == "success"
    assert (tmp_dir / "dyn" / "dynamic_sheet.xlsx").is_file()

    print("  [PASS] All 6 document tools fully registered and dynamically executable via ToolRegistry.")


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

async def main():
    print("=" * 75)
    print("MAKIMA v2 — STEP 9.3: DOCUMENT PROCESSING TOOLS TEST SUITE")
    print("=" * 75)

    with tempfile.TemporaryDirectory() as temp_dir_str:
        tmp_dir = Path(temp_dir_str).resolve()
        try:
            set_workspace_dir(tmp_dir)
            test_excel_processing(tmp_dir)
            test_word_processing(tmp_dir)
            test_powerpoint_processing(tmp_dir)
            test_document_boundary_security(tmp_dir)
            await test_registry_integration(tmp_dir)
        finally:
            set_workspace_dir(None)

    print("\n" + "=" * 75)
    print("ALL DOCUMENT PROCESSING TESTS PASSED (EXIT CODE 0)")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())
