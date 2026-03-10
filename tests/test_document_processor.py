"""
Tests for backend.services.document_processor.
Run from the project root:
    python -m pytest tests/test_document_processor.py -v
"""
import os
import sys

import pytest

# Ensure the project root is on sys.path when running directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.services.document_processor import extract_text, extract_text_from_bytes

SAMPLES = os.path.join(os.path.dirname(__file__), "sample_files")


# ---------------------------------------------------------------------------
# File-path based tests
# ---------------------------------------------------------------------------

def test_txt_extraction():
    text = extract_text(os.path.join(SAMPLES, "sample.txt"))
    assert "Hello from a text file" in text
    assert "line two" in text


def test_csv_extraction():
    text = extract_text(os.path.join(SAMPLES, "sample.csv"))
    assert "name" in text.lower()
    assert "Alice" in text
    assert "London" in text


def test_docx_extraction():
    text = extract_text(os.path.join(SAMPLES, "sample.docx"))
    assert "Document Analyzer" in text
    assert "extraction testing" in text


def test_pdf_extraction():
    # The sample PDF is blank (no embedded text layer), so we just verify
    # the function runs without error and returns a string.
    text = extract_text(os.path.join(SAMPLES, "sample.pdf"))
    assert isinstance(text, str)


def test_unsupported_type_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text(__file__, ".py")


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        extract_text(os.path.join(SAMPLES, "nonexistent.txt"))


# ---------------------------------------------------------------------------
# Bytes-based tests
# ---------------------------------------------------------------------------

def test_txt_bytes():
    data = b"Bytes TXT content line one.\nLine two."
    text = extract_text_from_bytes(data, ".txt")
    assert "Bytes TXT content" in text


def test_csv_bytes():
    data = b"col1,col2\nfoo,bar\nbaz,qux"
    text = extract_text_from_bytes(data, ".csv")
    assert "col1" in text
    assert "foo" in text


def test_docx_bytes():
    import docx as _docx
    import io
    doc = _docx.Document()
    doc.add_paragraph("Bytes DOCX paragraph.")
    buf = io.BytesIO()
    doc.save(buf)
    text = extract_text_from_bytes(buf.getvalue(), ".docx")
    assert "Bytes DOCX paragraph" in text


def test_pdf_bytes():
    with open(os.path.join(SAMPLES, "sample.pdf"), "rb") as f:
        data = f.read()
    text = extract_text_from_bytes(data, ".pdf")
    assert isinstance(text, str)
