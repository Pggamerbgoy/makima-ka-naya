import pypdf
import pytest
from makima.tools.documents.pdf import create_pdf_document, convert_docx_to_pdf
from makima.tools.documents.word import create_word_document
from makima.tools.filesystem.safe_io import set_workspace_dir


@pytest.fixture(autouse=True)
def setup_test_workspace(tmp_path):
    set_workspace_dir(tmp_path)
    yield
    set_workspace_dir(None)


def test_create_pdf_document(tmp_path):
    pdf_out = tmp_path / "test_doc.pdf"
    res = create_pdf_document(
        file_path="test_doc.pdf",
        title="Test Native PDF Document",
        sections=[
            {
                "heading": "Introduction",
                "level": 1,
                "text": "This is a native PDF generated without Microsoft Word.",
                "bullets": ["Bullet 1", "Bullet 2"],
            },
            {
                "heading": "Data Table",
                "level": 2,
                "table": {
                    "headers": ["Item", "Status"],
                    "rows": [["Task A", "Complete"], ["Task B", "In Progress"]],
                },
            },
        ],
    )
    assert res["status"] == "created"
    assert pdf_out.exists()

    reader = pypdf.PdfReader(str(pdf_out))
    assert len(reader.pages) >= 1
    content = reader.pages[0].extract_text()
    assert "Test Native PDF Document" in content
    assert "Introduction" in content


def test_convert_docx_to_pdf(tmp_path):
    docx_file = tmp_path / "sample.docx"
    create_word_document(
        file_path="sample.docx",
        title="Word Sample Document",
        sections=[
            {"heading": "Section 1", "text": "Paragraph text inside Word doc."},
        ],
    )
    assert docx_file.exists()

    pdf_file = tmp_path / "converted.pdf"
    res = convert_docx_to_pdf(docx_path="sample.docx", pdf_path="converted.pdf")
    assert res["status"] == "converted"
    assert pdf_file.exists()

    reader = pypdf.PdfReader(str(pdf_file))
    assert len(reader.pages) >= 1
    assert "Word Sample Document" in reader.pages[0].extract_text()


def test_serve_workspace_file_endpoint(tmp_path):
    from starlette.testclient import TestClient
    from makima.api.app import create_app

    # Create a test PDF in workspace
    test_pdf = tmp_path / "reports" / "summary.pdf"
    test_pdf.parent.mkdir(parents=True, exist_ok=True)
    create_pdf_document(
        file_path="reports/summary.pdf",
        title="Summary Report",
        sections=[{"heading": "Status", "text": "All systems operational"}],
    )
    assert test_pdf.exists()

    app = create_app()
    with TestClient(app) as client:
        # Happy path - inline PDF serving
        resp = client.get("/api/workspace/files/reports/summary.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert "inline" in resp.headers.get("content-disposition", "")
        assert resp.content.startswith(b"%PDF")

        # 404 for non-existent file
        resp_404 = client.get("/api/workspace/files/reports/missing.pdf")
        assert resp_404.status_code == 404

        # Path traversal prevention: Starlette client collapses /../../ to /secret.txt (404),
        # or URL-encoded /%2e%2e/ triggers 403 / 404.
        resp_encoded = client.get("/api/workspace/files/%2e%2e/secret.txt")
        assert resp_encoded.status_code in (403, 404)



