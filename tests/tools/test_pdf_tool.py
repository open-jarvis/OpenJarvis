"""Tests for the pdf_extract tool."""

from __future__ import annotations

import builtins
import sys
from unittest.mock import MagicMock

from friday_ai.tools.pdf_tool import PDFExtractTool, _parse_pages


class TestPDFExtractTool:
    def test_spec(self):
        tool = PDFExtractTool()
        assert tool.spec.name == "pdf_extract"
        assert tool.spec.category == "media"
        assert "file_path" in tool.spec.parameters["properties"]
        assert "file_path" in tool.spec.parameters["required"]
        assert tool.spec.required_capabilities == ["file:read"]

    def test_tool_id(self):
        tool = PDFExtractTool()
        assert tool.tool_id == "pdf_extract"

    def test_no_file_path(self):
        tool = PDFExtractTool()
        result = tool.execute(file_path="")
        assert result.success is False
        assert "No file_path" in result.content

    def test_no_file_path_param(self):
        tool = PDFExtractTool()
        result = tool.execute()
        assert result.success is False
        assert "No file_path" in result.content

    def test_file_not_found(self):
        tool = PDFExtractTool()
        result = tool.execute(file_path="/nonexistent/doc.pdf")
        assert result.success is False
        assert "File not found" in result.content

    def test_not_a_pdf(self, tmp_path):
        f = tmp_path / "document.txt"
        f.write_text("not a pdf", encoding="utf-8")
        tool = PDFExtractTool()
        result = tool.execute(file_path=str(f))
        assert result.success is False
        assert "Not a PDF" in result.content

    def test_pdfplumber_not_installed(self, tmp_path, monkeypatch):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake pdf content")

        monkeypatch.delitem(sys.modules, "pdfplumber", raising=False)
        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "pdfplumber":
                raise ImportError("No module named 'pdfplumber'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = PDFExtractTool()
        result = tool.execute(file_path=str(f))
        assert result.success is False
        assert "pdfplumber package not installed" in result.content

    def test_successful_extraction(self, tmp_path, monkeypatch):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake")

        # Mock pdfplumber
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page one text."
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page two text."

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf
        monkeypatch.setitem(sys.modules, "pdfplumber", mock_pdfplumber)

        tool = PDFExtractTool()
        result = tool.execute(file_path=str(f))
        assert result.success is True
        assert "Page one text." in result.content
        assert "Page two text." in result.content
        assert result.metadata["total_pages"] == 2
        assert result.metadata["pages_extracted"] == 2

    def test_extraction_with_page_range(self, tmp_path, monkeypatch):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake")

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "First page."
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Second page."
        mock_page3 = MagicMock()
        mock_page3.extract_text.return_value = "Third page."

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page1, mock_page2, mock_page3]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf
        monkeypatch.setitem(sys.modules, "pdfplumber", mock_pdfplumber)

        tool = PDFExtractTool()
        # Extract only pages 1 and 3 (1-indexed)
        result = tool.execute(file_path=str(f), pages="1,3")
        assert result.success is True
        assert "First page." in result.content
        assert "Third page." in result.content
        assert "Second page." not in result.content
        assert result.metadata["pages_extracted"] == 2

    def test_max_chars_truncation(self, tmp_path, monkeypatch):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake")

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "A" * 1000

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf
        monkeypatch.setitem(sys.modules, "pdfplumber", mock_pdfplumber)

        tool = PDFExtractTool()
        result = tool.execute(file_path=str(f), max_chars=100)
        assert result.success is True
        assert "[Content truncated]" in result.content
        # The content before truncation marker should be <= max_chars
        truncated_idx = result.content.index("\n\n[Content truncated]")
        assert truncated_idx == 100

    def test_pdf_extraction_error(self, tmp_path, monkeypatch):
        f = tmp_path / "bad.pdf"
        f.write_bytes(b"%PDF-1.4 corrupt")

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.side_effect = RuntimeError("Corrupt PDF")
        monkeypatch.setitem(sys.modules, "pdfplumber", mock_pdfplumber)

        tool = PDFExtractTool()
        result = tool.execute(file_path=str(f))
        assert result.success is False
        assert "PDF extraction error" in result.content

    def test_to_openai_function(self):
        tool = PDFExtractTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "pdf_extract"


class TestParsePages:
    def test_single_page(self):
        assert _parse_pages("3", 10) == [2]

    def test_range(self):
        assert _parse_pages("1-5", 10) == [0, 1, 2, 3, 4]

    def test_comma_separated(self):
        assert _parse_pages("1,3,5", 10) == [0, 2, 4]

    def test_mixed(self):
        result = _parse_pages("1-3,5", 10)
        assert result == [0, 1, 2, 4]

    def test_out_of_range_clamped(self):
        # Page 20 is out of range for a 5-page doc
        assert _parse_pages("20", 5) == []

    def test_range_clamped_to_total(self):
        # "1-100" on a 3-page doc should only return 3 pages
        assert _parse_pages("1-100", 3) == [0, 1, 2]

    def test_duplicates_removed(self):
        result = _parse_pages("1,1,2,2", 5)
        assert result == [0, 1]

    def test_empty_string(self):
        assert _parse_pages("", 5) == []
