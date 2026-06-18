"""
Tests for soveryn.platform.documents.render

Run order: md/html/pdf tests are fast and unconditional.
DOCX test is @pytest.mark.integration and skips if libreoffice is absent.
"""
import shutil
import pytest

from soveryn.platform.documents.render import (
    md_to_html,
    html_to_pdf,
    html_to_docx,
    render_document,
)


# ---------------------------------------------------------------------------
# md_to_html
# ---------------------------------------------------------------------------

class TestMdToHtml:
    def test_produces_h1(self):
        html = md_to_html("# Hello\n\n- a\n- b")
        assert "<h1>" in html

    def test_produces_text_content(self):
        html = md_to_html("# Hello\n\n- a\n- b")
        assert "Hello" in html

    def test_produces_ul(self):
        html = md_to_html("# Hello\n\n- a\n- b")
        assert "<ul>" in html

    def test_produces_li(self):
        html = md_to_html("# Hello\n\n- a\n- b")
        assert "<li>" in html

    def test_is_full_html_document(self):
        html = md_to_html("# Hello")
        assert "<html" in html.lower()
        assert "<body" in html.lower()
        assert "</html>" in html.lower()

    def test_title_appears_in_head(self):
        html = md_to_html("# Hello", title="My Doc")
        assert "My Doc" in html
        assert "<title>" in html

    def test_has_style_block(self):
        html = md_to_html("# Hello")
        assert "<style>" in html


# ---------------------------------------------------------------------------
# html_to_pdf
# ---------------------------------------------------------------------------

class TestHtmlToPdf:
    def test_returns_pdf_bytes(self):
        html = md_to_html("# Hi")
        result = html_to_pdf(html)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"

    def test_non_empty(self):
        html = md_to_html("# Hi\n\nSome content here.")
        result = html_to_pdf(html)
        assert len(result) > 1000  # a real PDF has heft


# ---------------------------------------------------------------------------
# render_document dispatcher
# ---------------------------------------------------------------------------

class TestRenderDocument:
    def test_md_format_returns_bytes_and_mime(self):
        data, mime = render_document("x", "md")
        assert data == b"x"
        assert mime == "text/markdown"

    def test_html_format_returns_html_bytes(self):
        data, mime = render_document("# T", "html")
        assert b"<h1>" in data
        assert mime == "text/html"

    def test_pdf_format_starts_with_pdf_magic(self):
        data, mime = render_document("# T", "pdf")
        assert data[:4] == b"%PDF"
        assert mime == "application/pdf"

    def test_unknown_format_raises_value_error(self):
        with pytest.raises(ValueError):
            render_document("x", "bogus")

    def test_html_format_content_is_full_doc(self):
        data, mime = render_document("# Hello\n\n- a", "html")
        assert b"<html" in data.lower()


# ---------------------------------------------------------------------------
# html_to_docx  (integration — skips if libreoffice absent)
# ---------------------------------------------------------------------------

LIBREOFFICE_AVAILABLE = shutil.which("libreoffice") is not None

@pytest.mark.integration
@pytest.mark.skipif(not LIBREOFFICE_AVAILABLE, reason="libreoffice not installed")
class TestHtmlToDocx:
    def test_returns_zip_magic(self):
        html = md_to_html("# Test Document\n\nHello world.")
        result = html_to_docx(html)
        assert isinstance(result, bytes)
        # DOCX is a zip; zip magic bytes are PK\x03\x04
        assert result[:2] == b"PK"

    def test_non_empty(self):
        html = md_to_html("# Test\n\nSome content.")
        result = html_to_docx(html)
        assert len(result) > 100

    def test_render_document_docx_format(self):
        data, mime = render_document("# DOCX Test", "docx")
        assert data[:2] == b"PK"
        assert mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
