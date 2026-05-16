"""
Tests for Gemini-backed analysis (mocked) and heuristic fallbacks.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.ai_analyzer import (  # noqa: E402
    ENTITY_KEYS,
    DocumentAnalysisResult,
    _parse_json_object,
    answer_question,
    extract_key_points,
    generate_summary,
    run_full_document_analysis,
)
from backend.services.document_analyzer import DocumentAnalyzer  # noqa: E402

SAMPLE_MARKETING = (ROOT / "tests" / "sample_docs" / "marketing_proposal.txt").read_text(
    encoding="utf-8"
)


def test_parse_json_strips_fence():
    raw = '```json\n{"summary": "Hello", "key_points": ["a"], "entities": {}}\n```'
    # _parse_json_object expects entities in full schema paths - use minimal fix
    data = _parse_json_object(raw)
    assert data["summary"] == "Hello"
    assert data["key_points"] == ["a"]


def test_fallback_when_no_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with patch("backend.services.ai_analyzer._reload_dotenv", lambda: None):
        result = run_full_document_analysis(SAMPLE_MARKETING)
    assert result.source == "fallback"
    assert "Q2" in result.summary or "campaign" in result.summary.lower()
    assert len(result.key_points) >= 1
    for k in ENTITY_KEYS:
        assert k in result.entities
        assert isinstance(result.entities[k], list)


def test_run_full_with_mocked_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    payload = {
        "summary": "Campaign targets millennials in Q2 2026.",
        "key_points": [
            "Budget: $150,000",
            "Platforms: Facebook, Instagram, TikTok",
        ],
        "entities": {
            "monetary_values": ["$150,000 (budget)", "$525,000 (projected revenue)"],
            "dates": ["Q2 2026", "April 1, 2026"],
            "organizations": ["Facebook Inc.", "Instagram LLC", "TikTok"],
            "key_metrics": ["3.5x ROI", "25–34 age range"],
        },
    }

    def fake_invoke(_prompt: str) -> str:
        return json.dumps(payload)

    with patch("backend.services.ai_analyzer._invoke_gemini", side_effect=fake_invoke):
        out = run_full_document_analysis(SAMPLE_MARKETING)

    assert out.source == "gemini"
    assert out.summary == payload["summary"]
    assert out.key_points == payload["key_points"]
    assert "$150,000" in out.entities["monetary_values"][0]


def test_document_analyzer_single_full_call(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    calls = {"n": 0}
    real = run_full_document_analysis

    def counting_run(text: str):
        calls["n"] += 1
        return real(text)

    with patch("backend.services.ai_analyzer._reload_dotenv", lambda: None):
        with patch(
            "backend.services.ai_analyzer.run_full_document_analysis",
            side_effect=counting_run,
        ):
            a = DocumentAnalyzer(SAMPLE_MARKETING)
            _ = a.summary()
            _ = a.key_points()
            _ = a.entities()
            assert calls["n"] == 1
            assert a.analysis_source() == "fallback"


def test_answer_question_empty_string():
    out = answer_question("some doc", "   ")
    assert "empty" in out.text.lower()
    assert out.source == "fallback"


def test_answer_question_fallback_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with patch("backend.services.ai_analyzer._reload_dotenv", lambda: None):
        out = answer_question(SAMPLE_MARKETING, "What is the total budget?")
    assert "GEMINI_API_KEY" in out.text or "unavailable" in out.text.lower()
    assert out.source == "fallback"


def test_answer_question_includes_followup_context_in_prompt(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    prompts: list[str] = []

    def capture_invoke(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"answer": "Acknowledged."})

    insights = {
        "summary": "Quarterly marketing plan.",
        "key_points": ["Budget $150k", "Launch in Q2"],
        "entities": {"dates": ["Q2 2026"]},
    }
    conversation = [{"question": "What is the budget?", "answer": "$150,000 per the proposal."}]

    with patch("backend.services.ai_analyzer._invoke_gemini", side_effect=capture_invoke):
        out = answer_question(
            SAMPLE_MARKETING,
            "Can you elaborate on the second key point?",
            insights=insights,
            conversation=conversation,
        )

    assert out.text == "Acknowledged."
    assert out.source == "gemini"
    assert len(prompts) == 1
    p0 = prompts[0]
    assert "PRIOR ANALYSIS" in p0
    assert "PRIOR Q&A" in p0
    assert "Budget $150k" in p0
    assert "What is the budget?" in p0
    assert "elaborate on the second key point" in p0


def test_answer_question_filler_skips_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    called = {"n": 0}

    def fail_invoke(_prompt: str) -> str:
        called["n"] += 1
        raise AssertionError("model should not run for filler")

    with patch("backend.services.ai_analyzer._invoke_gemini", side_effect=fail_invoke):
        out = answer_question(SAMPLE_MARKETING, "hmmm.")
    assert called["n"] == 0
    assert "not sure" in out.text.lower() or "specific" in out.text.lower()
    assert out.source == "fallback"


def test_generate_summary_delegates_to_full_mock(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    fake = DocumentAnalysisResult(
        summary="S",
        key_points=[],
        entities={k: [] for k in ENTITY_KEYS},
        source="gemini",
    )
    with patch(
        "backend.services.ai_analyzer.run_full_document_analysis",
        return_value=fake,
    ) as m:
        assert generate_summary("hello") == "S"
        m.assert_called_once_with("hello")


def test_extract_key_points_mock(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    fake = DocumentAnalysisResult(
        summary="",
        key_points=["one", "two"],
        entities={k: [] for k in ENTITY_KEYS},
        source="gemini",
    )
    with patch(
        "backend.services.ai_analyzer.run_full_document_analysis",
        return_value=fake,
    ):
        assert extract_key_points("x") == ["one", "two"]
