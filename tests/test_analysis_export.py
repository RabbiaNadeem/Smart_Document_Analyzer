"""Analysis export: PDF / DOCX builders and HTTP endpoints."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import app  # noqa: E402
from backend.services.analysis_export import build_analysis_docx, build_analysis_pdf  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def sample_payload():
    return {
        "document_name": "Proposal Q2.pdf",
        "analyzed_at": "2026-05-11T14:30:00.000Z",
        "summary": "Executive overview of the proposal.",
        "key_points": ["Budget approved", "Timeline Q2"],
        "entities": {
            "monetary_values": ["$50,000"],
            "dates": ["May 2026"],
            "organizations": ["Acme Corp"],
            "key_metrics": ["2x growth"],
        },
        "analysis_source": "gemini",
    }


def test_build_pdf_bytes():
    content, name = build_analysis_pdf(**sample_payload())
    assert name.endswith(".pdf")
    assert content[:5] == b"%PDF-"


def test_build_docx_bytes():
    content, name = build_analysis_docx(**sample_payload())
    assert name.endswith(".docx")
    assert content[:2] == b"PK"


def test_export_pdf_endpoint(client):
    r = client.post("/api/export/pdf", json=sample_payload())
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert "attachment" in r.headers.get("content-disposition", "").lower()
    assert r.content[:5] == b"%PDF-"


def test_export_docx_endpoint(client):
    r = client.post("/api/export/docx", json=sample_payload())
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "wordprocessingml" in ct
    assert "attachment" in r.headers.get("content-disposition", "").lower()
    assert r.content[:2] == b"PK"
