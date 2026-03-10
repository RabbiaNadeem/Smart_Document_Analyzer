import io
import os

import pandas as pd
import PyPDF2
import docx


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_text(file_path: str, file_type: str | None = None) -> str:
    """Extract readable text from a document file.

    Args:
        file_path: Absolute or relative path to the file, OR a raw filename
                   whose extension is used when ``file_type`` is not supplied.
        file_type:  Explicit extension (e.g. ``".pdf"``). If omitted the
                    extension is inferred from *file_path*.

    Returns:
        Extracted text as a single string (UTF-8, normalised whitespace).

    Raises:
        ValueError: Unsupported file type.
        FileNotFoundError: File does not exist at *file_path*.
    """
    ext = (file_type or os.path.splitext(file_path)[1]).lower().strip()

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    handlers = {
        ".pdf":  _extract_pdf,
        ".docx": _extract_docx,
        ".txt":  _extract_txt,
        ".csv":  _extract_csv,
    }

    if ext not in handlers:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: {', '.join(handlers)}"
        )

    return handlers[ext](file_path)


def extract_text_from_bytes(file_bytes: bytes, ext: str) -> str:
    """Extract text directly from bytes without writing to disk.

    Useful when the file is already in memory (e.g., right after upload).
    """
    ext = ext.lower().strip()

    handlers = {
        ".pdf":  _extract_pdf_bytes,
        ".docx": _extract_docx_bytes,
        ".txt":  _extract_txt_bytes,
        ".csv":  _extract_csv_bytes,
    }

    if ext not in handlers:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: {', '.join(handlers)}"
        )

    return handlers[ext](file_bytes)


# ---------------------------------------------------------------------------
# File-path based helpers
# ---------------------------------------------------------------------------

def _extract_pdf(file_path: str) -> str:
    with open(file_path, "rb") as fh:
        return _extract_pdf_bytes(fh.read())


def _extract_docx(file_path: str) -> str:
    with open(file_path, "rb") as fh:
        return _extract_docx_bytes(fh.read())


def _extract_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
        return _normalise(fh.read())


def _extract_csv(file_path: str) -> str:
    with open(file_path, "rb") as fh:
        return _extract_csv_bytes(fh.read())


# ---------------------------------------------------------------------------
# Bytes-based helpers
# ---------------------------------------------------------------------------

def _extract_pdf_bytes(data: bytes) -> str:
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return _normalise("\n".join(pages))


def _extract_docx_bytes(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    paragraphs = [para.text for para in document.paragraphs if para.text.strip()]
    return _normalise("\n".join(paragraphs))


def _extract_txt_bytes(data: bytes) -> str:
    return _normalise(data.decode("utf-8", errors="replace"))


def _extract_csv_bytes(data: bytes) -> str:
    df = pd.read_csv(io.BytesIO(data))
    # Build a human-readable representation: header + rows
    lines: list[str] = [", ".join(df.columns.astype(str))]
    for _, row in df.iterrows():
        lines.append(", ".join(row.astype(str)))
    return _normalise("\n".join(lines))


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Strip leading/trailing whitespace and collapse excessive blank lines."""
    lines = text.splitlines()
    result: list[str] = []
    blank_run = 0
    for line in lines:
        stripped = line.rstrip()
        if stripped == "":
            blank_run += 1
            if blank_run <= 1:          # allow at most one consecutive blank line
                result.append("")
        else:
            blank_run = 0
            result.append(stripped)
    return "\n".join(result).strip()
