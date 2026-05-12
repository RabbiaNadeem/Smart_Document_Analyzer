"""Document analysis: extractive summary, key sentences, and named entities.

Uses spaCy (``en_core_web_sm``) for NER and (when possible) sentence boundaries.
Dense résumés / PDF text often lacks real sentence breaks; we then split on
paragraphs, clause boundaries, and bullets before ranking segments.

Public API (stable for ``/api/analyze``):
  ``__init__(text: str)``
  ``.summary()``    -> str
  ``.key_points()`` -> list[str]
  ``.entities()``   -> dict with keys people, organizations, locations
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache

_MAX_TEXT_CHARS = 600_000

# Summary: short, stable length (characters) — not a full document echo.
_SUMMARY_MAX_CHARS = 420
_SUMMARY_MAX_SEGMENTS = 2
_KEY_POINT_COUNT = 5
_KEY_POINT_MAX_CHARS = 180
_KEY_POINT_SENTENCES = 6
_MIN_SENTENCE_WORDS = 5

# When the longest spaCy sentence is below this, trust ``doc.sents``.
_LONG_SENTENCE_THRESHOLD = 480


@lru_cache(maxsize=1)
def _nlp():
    import spacy

    try:
        return spacy.load("en_core_web_sm")
    except OSError as exc:
        raise OSError(
            "spaCy English model is missing. Install with:\n"
            "  python -m spacy download en_core_web_sm"
        ) from exc


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        text = " ".join(raw.split())
        if len(text) < 2:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_boilerplate_segment(text: str) -> bool:
    """Skip contact lines, bare URLs, and similar non-summary noise."""
    t = _normalize_ws(text)
    if len(t) < 14:
        return True
    tl = t.casefold()
    if "http://" in tl or "https://" in tl or "www." in tl:
        return True
    if "linkedin.com" in tl or "github.com" in tl or "mailto:" in tl:
        return True
    if re.search(r"\S+@\S+\.\S+", t):
        return True
    # Mostly phone / digits
    if re.fullmatch(r"[\d\s\-+().]{12,}", t.strip()):
        return True
    if len(t) < 90 and re.search(r"\+?\d[\d\-\s().]{10,}\d", t):
        digitish = sum(c.isdigit() or c.isspace() for c in t) / max(len(t), 1)
        if digitish > 0.45:
            return True
    return False


def _segment_blocks(raw: str) -> list[str]:
    """Split dense résumé / PDF blobs into scorable segments."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return []

    blocks: list[str] = []

    def push_piece(piece: str) -> None:
        piece = piece.strip()
        if len(piece) < 22:
            return
        if len(piece) > 520:
            for chunk in re.split(r"\s*[;•·]\s*|\s*\|\s*", piece):
                chunk = chunk.strip()
                if len(chunk) >= 22:
                    blocks.append(chunk)
        else:
            blocks.append(piece)

    parts = re.split(r"\n{2,}", raw)
    if len(parts) == 1 and len(raw) > 600 and "\n" not in raw.strip():
        # Single-line wall of text: split on sentence punctuation.
        parts = re.split(r"(?<=[.!?])\s+", raw)

    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > 520:
            subs = re.split(r"(?<=[.!?])\s+", p)
            if len(subs) <= 1:
                subs = re.split(r"\s*[;•·]\s*|\n+", p)
            for s in subs:
                push_piece(s)
        else:
            push_piece(p)

    # De-duplicate neighbouring duplicates
    out: list[str] = []
    prev_cf = ""
    for b in blocks:
        cf = _normalize_ws(b).casefold()
        if cf == prev_cf:
            continue
        prev_cf = cf
        out.append(_normalize_ws(b))
    return out


def _word_freq_from_doc(doc) -> tuple[Counter[str], int]:
    wf: Counter[str] = Counter()
    for t in doc:
        if t.is_alpha and not t.is_stop and len(t.text) > 1:
            wf[t.text.lower()] += 1
    mx = max(wf.values()) if wf else 1
    return wf, mx


def _score_segment_words(seg: str, wf: Counter[str], max_wf: int) -> float:
    words = re.findall(r"[A-Za-z]{2,}", seg.lower())
    if not words:
        return 0.0
    score = sum(wf.get(w, 0) for w in words) / max_wf / math.sqrt(len(words))
    # Slight bias toward substantive length (not too long).
    ln = len(seg)
    if ln > 450:
        score *= 0.65
    elif ln < 120:
        score *= 1.08
    return score


def _truncate_words(text: str, max_chars: int) -> str:
    t = _normalize_ws(text)
    if len(t) <= max_chars:
        return t
    cut = t[: max_chars + 1]
    sp = cut.rfind(" ")
    if sp > max_chars // 2:
        cut = cut[:sp]
    else:
        cut = cut[:max_chars]
    return cut.rstrip(",;:") + "…"


def _sentence_lemmas(sent) -> list[str]:
    return [
        t.lemma_.lower()
        for t in sent
        if t.is_alpha and not t.is_stop and len(t.lemma_) > 1
    ]


def _sent_text(sent) -> str:
    return " ".join(sent.text.split())


def _score_sentences(sents, lemma_freq: Counter[str], max_freq: int):
    if max_freq <= 0:
        max_freq = 1
    scored: list[tuple[object, float]] = []
    for i, sent in enumerate(sents):
        lemmas = _sentence_lemmas(sent)
        if not lemmas:
            base = 0.0
        else:
            tf = sum(lemma_freq.get(lemma, 0) / max_freq for lemma in lemmas)
            base = tf / math.sqrt(len(lemmas))
        position_bonus = 1.0 + 0.12 * math.exp(-i / 4.0)
        scored.append((sent, base * position_bonus))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _pick_summary_sents(ranked, min_chars: int, max_chars: int, max_sentences: int):
    chosen: list = []
    length = 0
    for sent, _ in ranked:
        if len(chosen) >= max_sentences:
            break
        piece = _sent_text(sent)
        if len(piece) < 20:
            continue
        chosen.append(sent)
        length += len(piece) + 1
        if length >= min_chars and len(chosen) >= 2:
            break
        if length >= max_chars:
            break
    if not chosen and ranked:
        chosen = [ranked[0][0]]
    return chosen


def _pick_key_point_sents(ranked, exclude: set, n: int):
    out: list = []
    for sent, _ in ranked:
        if sent in exclude:
            continue
        text = _sent_text(sent)
        word_count = len(text.split())
        if word_count < _MIN_SENTENCE_WORDS:
            continue
        out.append(sent)
        if len(out) >= n:
            break
    return out


def _max_summary_sentence_count(num_sents: int) -> int:
    if num_sents <= 2:
        return min(2, num_sents)
    if num_sents >= 8:
        return min(3, num_sents // 2)
    return 2


class DocumentAnalyzer:
    """Analyses pre-extracted plain text from a document."""

    def __init__(self, text: str) -> None:
        raw = (text or "").strip()
        self._text = raw[:_MAX_TEXT_CHARS]
        self._doc = None
        # Populated by ``summary()`` so ``key_points()`` can skip duplicates.
        self._summary_segment_keys: set[str] = set()
        if self._text:
            self._doc = _nlp()(self._text)

    def _segments_for_extractive(self) -> list[str]:
        """Prefer spaCy sentences when short; otherwise structural segments."""
        if not self._doc:
            return []
        sents = [s for s in self._doc.sents if _sent_text(s).strip()]
        if not sents:
            return _segment_blocks(self._text)

        longest = max(len(_sent_text(s)) for s in sents)
        if len(sents) >= 2 and longest < _LONG_SENTENCE_THRESHOLD:
            return [_normalize_ws(_sent_text(s)) for s in sents]

        return _segment_blocks(self._text)

    def _ranked_content_segments(self) -> list[str]:
        segs = [s for s in self._segments_for_extractive() if not _is_boilerplate_segment(s)]
        if not self._doc:
            return segs
        wf, mx = _word_freq_from_doc(self._doc)
        segs.sort(key=lambda s: _score_segment_words(s, wf, mx), reverse=True)
        return segs

    def _set_summary_segments(self, parts: list[str]) -> None:
        self._summary_segment_keys = {
            _normalize_ws(p).casefold() for p in parts if _normalize_ws(p)
        }

    def summary(self) -> str:
        """Concise extractive summary (never the full document)."""
        self._summary_segment_keys = set()

        if not self._doc or not self._text.strip():
            return "No extractable text was found in this document."

        sents = [s for s in self._doc.sents if _sent_text(s).strip()]
        if not sents:
            segs = [s for s in _segment_blocks(self._text) if not _is_boilerplate_segment(s)]
            if not segs:
                self._set_summary_segments([_truncate_words(self._text, _SUMMARY_MAX_CHARS)])
                return _truncate_words(self._text, _SUMMARY_MAX_CHARS)
            wf, mx = _word_freq_from_doc(self._doc)
            segs.sort(key=lambda s: _score_segment_words(s, wf, mx), reverse=True)
            picked = segs[:_SUMMARY_MAX_SEGMENTS]
            self._set_summary_segments(picked)
            body = " ".join(picked)
            return _truncate_words(body, _SUMMARY_MAX_CHARS)

        longest = max(len(_sent_text(s)) for s in sents)

        # Dense blob: rank structural segments, not one giant "sentence".
        if len(sents) == 1 or longest >= _LONG_SENTENCE_THRESHOLD:
            ranked_segs = self._ranked_content_segments()
            if not ranked_segs:
                t = _normalize_ws(_sent_text(sents[0]))
                self._set_summary_segments([t])
                return _truncate_words(t, _SUMMARY_MAX_CHARS)
            parts: list[str] = []
            total = 0
            for seg in ranked_segs[: max(4, _SUMMARY_MAX_SEGMENTS + 2)]:
                if _is_boilerplate_segment(seg):
                    continue
                if not parts:
                    parts.append(seg)
                    total += len(seg)
                    continue
                if seg.casefold() in {p.casefold() for p in parts}:
                    continue
                if total + len(seg) > _SUMMARY_MAX_CHARS + 80:
                    break
                parts.append(seg)
                total += len(seg)
                if len(parts) >= _SUMMARY_MAX_SEGMENTS:
                    break
            if not parts:
                parts = [ranked_segs[0]]
            self._set_summary_segments(parts)
            body = " ".join(_normalize_ws(p) for p in parts)
            return _truncate_words(body, _SUMMARY_MAX_CHARS)

        # Normal multi-sentence document: short extractive summary.
        lemmas = [
            t.lemma_.lower()
            for t in self._doc
            if t.is_alpha and not t.is_stop and len(t.lemma_) > 1
        ]
        lemma_freq = Counter(lemmas)
        max_freq = max(lemma_freq.values()) if lemma_freq else 1
        ranked = _score_sentences(sents, lemma_freq, max_freq)
        max_summary = _max_summary_sentence_count(len(sents))
        picked = _pick_summary_sents(ranked, 120, 360, max_sentences=max_summary)
        if not picked:
            picked = [sents[0]]
        order = {id(s): i for i, s in enumerate(sents)}
        picked.sort(key=lambda s: order[id(s)])
        body = " ".join(_sent_text(s) for s in picked)
        body = _normalize_ws(body)
        self._set_summary_segments([_sent_text(s) for s in picked])
        return _truncate_words(body, _SUMMARY_MAX_CHARS)

    def key_points(self) -> list[str]:
        """Short bullets; skips boilerplate and segments already used in the summary."""
        if not self._doc or not self._text.strip():
            return []

        _ = self.summary()

        sents = [s for s in self._doc.sents if _sent_text(s).strip()]
        longest = max((len(_sent_text(s)) for s in sents), default=0)

        points: list[str] = []

        if len(sents) <= 1 or longest >= _LONG_SENTENCE_THRESHOLD:
            ranked_segs = self._ranked_content_segments()
            used: set[str] = set()
            banned = self._summary_segment_keys
            for seg in ranked_segs:
                line = _truncate_words(seg, _KEY_POINT_MAX_CHARS)
                if _is_boilerplate_segment(line):
                    continue
                key = line.casefold()
                if key in used or key in banned:
                    continue
                used.add(key)
                points.append(line)
                if len(points) >= _KEY_POINT_COUNT:
                    break
            return points[:_KEY_POINT_SENTENCES]

        lemmas = [
            t.lemma_.lower()
            for t in self._doc
            if t.is_alpha and not t.is_stop and len(t.lemma_) > 1
        ]
        lemma_freq = Counter(lemmas)
        max_freq = max(lemma_freq.values()) if lemma_freq else 1
        ranked = _score_sentences(sents, lemma_freq, max_freq)
        max_summary = _max_summary_sentence_count(len(sents))
        summary_sents = set(_pick_summary_sents(ranked, 120, 360, max_sentences=max_summary))
        kp_sents = _pick_key_point_sents(ranked, summary_sents, _KEY_POINT_SENTENCES)

        for sent in kp_sents:
            line = _sent_text(sent)
            if line.endswith("."):
                line = line[:-1].strip()
            line = _truncate_words(line, _KEY_POINT_MAX_CHARS)
            if line and not _is_boilerplate_segment(line):
                points.append(line)

        if not points and len(sents) >= 2:
            summary_norm = {_sent_text(s).casefold() for s in summary_sents}
            for s in sents:
                t = _sent_text(s)
                if t.casefold() in summary_norm:
                    continue
                if len(t.split()) >= max(4, _MIN_SENTENCE_WORDS - 1):
                    points.append(_truncate_words(t.rstrip("."), _KEY_POINT_MAX_CHARS))
                if len(points) >= _KEY_POINT_SENTENCES:
                    break

        if not points:
            skip = min(len(ranked), max_summary)
            for sent, _ in ranked[skip : skip + _KEY_POINT_SENTENCES * 2]:
                t = _truncate_words(_sent_text(sent).rstrip("."), _KEY_POINT_MAX_CHARS)
                if t and t not in points and not _is_boilerplate_segment(t):
                    points.append(t)
                if len(points) >= _KEY_POINT_SENTENCES:
                    break

        return points[:_KEY_POINT_SENTENCES]

    def entities(self) -> dict:
        """Named entities grouped for the API contract."""
        empty = {"people": [], "organizations": [], "locations": []}
        if not self._doc:
            return empty

        people: list[str] = []
        orgs: list[str] = []
        locs: list[str] = []

        for ent in self._doc.ents:
            label = ent.label_
            text = ent.text.strip()
            if len(text) < 2:
                continue
            if label == "PERSON":
                people.append(text)
            elif label == "ORG":
                orgs.append(text)
            elif label in ("GPE", "LOC", "FAC"):
                locs.append(text)

        return {
            "people": _dedupe_preserve_order(people),
            "organizations": _dedupe_preserve_order(orgs),
            "locations": _dedupe_preserve_order(locs),
        }
