"""High-level document analysis facade over the Gemini AI layer."""

from __future__ import annotations

from typing import Any

from backend.services import ai_analyzer


class DocumentAnalyzer:
    """Analyses pre-extracted text: summary, key points, entities, and Q&A.

    Full analysis (summary + key points + entities) is computed once per
    instance and cached. ``answer_question`` uses a separate model call.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._cached: ai_analyzer.DocumentAnalysisResult | None = None

    def _analysis(self) -> ai_analyzer.DocumentAnalysisResult:
        if self._cached is None:
            self._cached = ai_analyzer.run_full_document_analysis(self._text)
        return self._cached

    def summary(self) -> str:
        return self._analysis().summary

    def key_points(self) -> list[str]:
        return list(self._analysis().key_points)

    def entities(self) -> dict:
        """Structured buckets aligned with the results dashboard."""
        return {k: list(v) for k, v in self._analysis().entities.items()}

    def analysis_source(self) -> str:
        """``gemini`` or ``fallback`` (no key / model error)."""
        return self._analysis().source

    def answer_question(
        self,
        question: str,
        *,
        insights: dict[str, Any] | None = None,
        conversation: list[dict[str, str]] | None = None,
    ) -> ai_analyzer.QuestionAnswer:
        return ai_analyzer.answer_question(
            self._text,
            question,
            insights=insights,
            conversation=conversation,
        )
