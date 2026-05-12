"""
Gemini-powered document analysis: structured JSON outputs with fallbacks.

Environment:
    GEMINI_API_KEY   — required for live model calls (never commit).
    GOOGLE_API_KEY   — accepted as an alias for ``GEMINI_API_KEY``.
    GEMINI_MODEL     — optional; default ``gemini-2.5-flash``. If that model hits
                       quota limits, ``gemini-flash-latest`` and ``gemini-3.1-flash-lite``
                       are tried automatically.

``.env`` is reloaded before each analysis so you do not always need to restart
uvicorn after editing the key (restart is still recommended if behavior seems stuck).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default model: 2.0-flash often hits free-tier "limit: 0" quota; 2.5-flash is a
# practical default for AI Studio keys (verify with list_models if needed).
DEFAULT_MODEL = "gemini-2.5-flash"
# Tried in order after the primary (env GEMINI_MODEL or default) on 429 quota.
_MODEL_QUOTA_FALLBACKS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
)
MAX_DOCUMENT_CHARS = 80_000

ENTITY_KEYS = ("monetary_values", "dates", "organizations", "key_metrics")


@dataclass(frozen=True)
class DocumentAnalysisResult:
    """Structured output from a full document analysis run."""

    summary: str
    key_points: list[str]
    entities: dict[str, list[str]]
    source: str  # "gemini" | "fallback"


# ---------------------------------------------------------------------------
# Prompts (JSON-only responses)
# ---------------------------------------------------------------------------

_FULL_ANALYSIS_INSTRUCTIONS = """You are an expert business-document analyst.
Read the document text and return ONE JSON object only (no markdown fences, no commentary).

Schema (all keys required):
{
  "summary": "<2–5 sentence executive summary in plain prose. No bullet characters.>",
  "key_points": ["<concise fact 1>", "<fact 2>", ...],
  "entities": {
    "monetary_values": ["<e.g. $150,000 (budget)>"],
    "dates": ["<e.g. Q2 2026>", "<April 1, 2026>"],
    "organizations": ["<company or brand names as they appear>"],
    "key_metrics": ["<e.g. 3.5x ROI>", "<25–34 age range>"]
  }
}

Rules:
- Base every field ONLY on the supplied document. Do not invent facts.
- If a category has nothing in the text, use an empty array [].
- key_points: 5–12 items when the document is rich enough; fewer for short docs.
- Keep strings short and scannable (dashboard display).
- monetary_values: include currency symbols and brief context in parentheses when useful.
"""


_ANSWER_INSTRUCTIONS = """You answer questions using ONLY the provided document.
If the document does not contain enough information, respond with a short sentence stating that the document does not specify this.

Return ONE JSON object: {"answer": "<plain text, 1–4 sentences, no markdown>"}
No markdown fences, no extra keys."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_full_document_analysis(document_text: str) -> DocumentAnalysisResult:
    """Single Gemini call returning summary, key points, and categorized entities."""
    body = _truncate(document_text)
    if not _gemini_configured():
        logger.info("No Gemini API key in environment; using heuristic fallback analysis.")
        return _fallback_to_result(_fallback_full(body, reason="missing_key"))

    prompt = (
        _FULL_ANALYSIS_INSTRUCTIONS
        + "\n\n--- DOCUMENT START ---\n"
        + body
        + "\n--- DOCUMENT END ---\n"
    )
    try:
        raw = _invoke_gemini(prompt)
        data = _parse_json_object(raw)
        normalized = _normalize_full_payload(data, body)
        return DocumentAnalysisResult(
            summary=normalized["summary"],
            key_points=normalized["key_points"],
            entities=normalized["entities"],
            source="gemini",
        )
    except Exception:
        logger.exception("Gemini full analysis failed; using fallback.")
        return _fallback_to_result(_fallback_full(body, reason="api_error"))


def generate_summary(document_text: str) -> str:
    """Return an executive summary (uses the same full analysis pipeline)."""
    return run_full_document_analysis(document_text).summary


def extract_key_points(document_text: str) -> list[str]:
    """Return bullet-ready key points."""
    return list(run_full_document_analysis(document_text).key_points)


def extract_entities(document_text: str) -> dict[str, list[str]]:
    """Return entities grouped by monetary_values, dates, organizations, key_metrics."""
    return {k: list(v) for k, v in run_full_document_analysis(document_text).entities.items()}


def answer_question(document_text: str, question: str) -> str:
    """Answer a natural-language question strictly from the document."""
    q = (question or "").strip()
    if not q:
        return "Please provide a non-empty question."

    body = _truncate(document_text)
    if not _gemini_configured():
        return _fallback_answer(body, q, reason="missing_key")

    prompt = (
        _ANSWER_INSTRUCTIONS
        + "\n\n--- DOCUMENT START ---\n"
        + body
        + "\n--- DOCUMENT END ---\n\nQUESTION:\n"
        + q
    )
    try:
        raw = _invoke_gemini(prompt)
        data = _parse_json_object(raw)
        ans = data.get("answer")
        if isinstance(ans, str) and ans.strip():
            return ans.strip()
        return _fallback_answer(body, q, reason="api_error")
    except Exception:
        logger.exception("Gemini Q&A failed; using fallback answer.")
        return _fallback_answer(body, q, reason="api_error")


# ---------------------------------------------------------------------------
# Gemini transport
# ---------------------------------------------------------------------------


def _reload_dotenv() -> None:
    """Load ``.env`` from the project root first (cwd-independent), then find_dotenv."""
    try:
        from dotenv import find_dotenv, load_dotenv

        root_env = Path(__file__).resolve().parents[2] / ".env"
        if root_env.is_file():
            load_dotenv(root_env, override=False)
            return
        path = find_dotenv(usecwd=True)
        if path:
            load_dotenv(path, override=False)
    except ImportError:
        pass


def _api_key() -> str:
    _reload_dotenv()
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def _gemini_configured() -> bool:
    return bool(_api_key())


def _model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _invoke_gemini(prompt: str) -> str:
    import google.generativeai as genai
    from google.api_core import exceptions as google_exceptions

    key = _api_key()
    if not key:
        raise ValueError("Gemini API key is not configured")
    genai.configure(api_key=key)

    primary = _model_name()
    candidates: list[str] = []
    for m in (primary, *_MODEL_QUOTA_FALLBACKS):
        if m and m not in candidates:
            candidates.append(m)

    last_error: Exception | None = None
    for model_id in candidates:
        try:
            model = genai.GenerativeModel(
                model_id,
                generation_config={
                    "temperature": 0.25,
                    "top_p": 0.95,
                    "response_mime_type": "application/json",
                },
            )
            response = model.generate_content(
                prompt,
                request_options={"timeout": 120},
            )
            return _extract_text_from_response(response)
        except google_exceptions.ResourceExhausted as exc:
            last_error = exc
            logger.warning(
                "Gemini model %r hit quota/rate limits; trying next fallback if any.",
                model_id,
            )
            continue
        except Exception:
            raise

    assert last_error is not None
    raise last_error


def _extract_text_from_response(response: object) -> str:
    t = getattr(response, "text", None)
    if isinstance(t, str) and t.strip():
        return t.strip()
    cands = getattr(response, "candidates", None) or []
    if not cands:
        raise ValueError("No candidates in model response")
    content = getattr(cands[0], "content", None)
    parts = getattr(content, "parts", None) if content else None
    if not parts:
        raise ValueError("Empty model response")
    chunks: list[str] = []
    for part in parts:
        tx = getattr(part, "text", None)
        if isinstance(tx, str) and tx:
            chunks.append(tx)
    joined = "".join(chunks).strip()
    if not joined:
        raise ValueError("Empty model response parts")
    return joined


# ---------------------------------------------------------------------------
# JSON parsing & normalization
# ---------------------------------------------------------------------------


def _parse_json_object(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise TypeError("JSON root must be an object")
    return data


def _normalize_full_payload(data: dict[str, Any], document_body: str) -> dict[str, Any]:
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = _fallback_full(document_body)["summary"]

    kps = data.get("key_points")
    key_points = _normalize_string_list(kps, max_items=20)
    if not key_points:
        key_points = _fallback_full(document_body)["key_points"]

    raw_ent = data.get("entities")
    entities: dict[str, list[str]] = {k: [] for k in ENTITY_KEYS}
    if isinstance(raw_ent, dict):
        for key in ENTITY_KEYS:
            entities[key] = _normalize_string_list(raw_ent.get(key), max_items=30)

    return {"summary": summary.strip(), "key_points": key_points, "entities": entities}


def _normalize_string_list(value: Any, *, max_items: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) and value.strip():
        return [value.strip()[:500]]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:500])
        elif isinstance(item, (int, float)):
            out.append(str(item))
        if len(out) >= max_items:
            break
    return out


def _fallback_to_result(data: dict[str, Any]) -> DocumentAnalysisResult:
    ent = data.get("entities") or {}
    entities = {k: list(ent.get(k) or []) for k in ENTITY_KEYS}
    return DocumentAnalysisResult(
        summary=str(data.get("summary") or ""),
        key_points=list(data.get("key_points") or []),
        entities=entities,
        source="fallback",
    )


# ---------------------------------------------------------------------------
# Heuristic fallbacks (no API)
# ---------------------------------------------------------------------------


def _truncate(text: str) -> str:
    t = text or ""
    if len(t) <= MAX_DOCUMENT_CHARS:
        return t
    return t[:MAX_DOCUMENT_CHARS] + "\n\n[... document truncated for analysis ...]"


def _fallback_full(document_body: str, *, reason: str = "generic") -> dict[str, Any]:
    snippet = (document_body or "").strip()
    if not snippet:
        return {
            "summary": "No readable text was found in this document.",
            "key_points": [],
            "entities": {k: [] for k in ENTITY_KEYS},
        }

    para = snippet.replace("\r\n", "\n").replace("\r", "\n")
    first_block = para.split("\n\n")[0].strip()
    if len(first_block) > 900:
        first_block = first_block[:897].rsplit(" ", 1)[0] + "…"

    sentences = re.split(r"(?<=[.!?])\s+", para)
    bullets: list[str] = []
    for s in sentences:
        s = s.strip()
        if len(s) < 20:
            continue
        bullets.append(s[:280] + ("…" if len(s) > 280 else ""))
        if len(bullets) >= 8:
            break
    if not bullets:
        bullets = [para[:400] + ("…" if len(para) > 400 else "")]

    if reason == "missing_key":
        prefix = (
            "Gemini is not configured: set GEMINI_API_KEY (or GOOGLE_API_KEY) in your "
            "project root `.env` file, save it, then click **Analyze** again. "
            "If it still shows this message, restart the uvicorn process so the "
            "environment reloads. "
        )
    elif reason == "api_error":
        prefix = (
            "The AI request failed (invalid key, quota, network, model name, or blocked "
            "response). Check the server terminal logs, verify GEMINI_MODEL "
            f"(currently {_model_name()!r}), and try again. "
        )
    else:
        prefix = "This document could not be analyzed with the AI service. "

    return {
        "summary": prefix + f"Opening excerpt: {first_block}",
        "key_points": bullets,
        "entities": {k: [] for k in ENTITY_KEYS},
    }


def _fallback_answer(document_body: str, question: str, *, reason: str = "missing_key") -> str:
    if not (document_body or "").strip():
        return "The document has no extractable text to search."
    if reason == "api_error":
        return (
            "Gemini could not answer this question (see server logs). "
            "Check your API key, quota, and GEMINI_MODEL, then try again."
        )
    return (
        "Gemini Q&A is not configured: add GEMINI_API_KEY (or GOOGLE_API_KEY) to `.env`, "
        "save, and try again (or restart uvicorn)."
    )

