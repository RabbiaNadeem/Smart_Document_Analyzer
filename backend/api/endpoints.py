import logging
import os
import uuid
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.services.analysis_export import build_analysis_docx, build_analysis_pdf
from backend.services.document_analyzer import DocumentAnalyzer
from backend.services.document_processor import extract_text_from_bytes
from backend.services.supabase_service import download_from_storage, upload_to_storage

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS: set[str] = {".pdf", ".docx", ".txt", ".csv"}

# Content-Type values clients may send for each allowed type
ALLOWED_MIME_TYPES: set[str] = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/csv",
    "application/csv",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Cap extracted text returned to clients (full text is still used for analysis).
EXTRACTED_TEXT_PREVIEW_MAX = 12_000

# Magic-byte signatures for binary formats (offset 0)
_MAGIC_BYTES: dict[str, bytes] = {
    ".pdf": b"%PDF",
    ".docx": b"PK\x03\x04",  # DOCX is a ZIP archive
}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)) -> dict:
    # --- Filename / extension check ---
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Accepted formats: PDF, DOCX, TXT, CSV.",
        )

    # --- MIME type check ---
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid MIME type '{file.content_type}'. "
                   "Accepted: application/pdf, application/vnd.openxmlformats-officedocument"
                   ".wordprocessingml.document, text/plain, text/csv.",
        )

    # --- Read in chunks (enforces 10 MB limit without loading full file at once) ---
    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = await file.read(65_536)  # 64 KB
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="File too large. Maximum allowed size is 10 MB.",
            )
        chunks.append(chunk)

    file_bytes = b"".join(chunks)

    # --- Empty-file guard ---
    if total_size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # --- Magic-byte validation for binary formats ---
    if ext in _MAGIC_BYTES:
        if not file_bytes.startswith(_MAGIC_BYTES[ext]):
            raise HTTPException(
                status_code=400,
                detail=f"File content does not match the expected binary signature for {ext}.",
            )

    # --- Upload to Supabase Storage ---
    file_id = str(uuid.uuid4())
    destination_path = f"uploads/{file_id}{ext}"

    try:
        upload_to_storage(file_bytes, destination_path, file.content_type)
    except Exception:
        logger.exception("Failed to upload file_id=%s to storage", file_id)
        raise HTTPException(
            status_code=502,
            detail="Failed to persist file to storage. Please try again.",
        )

    return {"file_id": file_id, "file_ext": ext, "message": "Upload successful"}


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    file_id: str
    file_ext: str


@router.post("/analyze")
async def analyze_document(request: AnalyzeRequest) -> dict:
    # --- Validate extension ---
    if request.file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid file extension '{request.file_ext}'. "
                f"Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
            ),
        )

    try:
        # --- Download file bytes from storage ---
        try:
            file_bytes = download_from_storage(request.file_id, request.file_ext)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"No file found for file_id '{request.file_id}'.",
            )

        # --- Extract text ---
        try:
            text = extract_text_from_bytes(file_bytes, request.file_ext)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        # --- Analyse (Gemini via DocumentAnalyzer; heuristic fallback if unavailable) ---
        analyzer = DocumentAnalyzer(text)
        preview = text[:EXTRACTED_TEXT_PREVIEW_MAX]
        truncated = len(text) > EXTRACTED_TEXT_PREVIEW_MAX
        return {
            "summary": analyzer.summary(),
            "key_points": analyzer.key_points(),
            "entities": analyzer.entities(),
            "document_id": request.file_id,
            "analysis_source": analyzer.analysis_source(),
            "extracted_text_preview": preview,
            "extracted_text_truncated": truncated,
            "extracted_text_length": len(text),
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Unexpected error during document analysis for file_id=%s", request.file_id
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during analysis.",
        )


# ---------------------------------------------------------------------------
# Ask (Q&A on uploaded document)
# ---------------------------------------------------------------------------


class QATurn(BaseModel):
    question: str
    answer: str


class AnalysisInsightsPayload(BaseModel):
    """Prior analysis from ``POST /api/analyze`` — improves follow-up Q&A."""

    summary: str | None = None
    key_points: list[str] | None = None
    entities: dict[str, list[str]] | None = None


class AskRequest(BaseModel):
    file_id: str
    file_ext: str
    question: str
    insights: AnalysisInsightsPayload | None = None
    conversation: list[QATurn] | None = None


@router.post("/ask")
async def ask_document(request: AskRequest) -> dict:
    q = (request.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    if request.file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid file extension '{request.file_ext}'. "
                f"Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
            ),
        )

    try:
        try:
            file_bytes = download_from_storage(request.file_id, request.file_ext)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"No file found for file_id '{request.file_id}'.",
            )

        try:
            text = extract_text_from_bytes(file_bytes, request.file_ext)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        analyzer = DocumentAnalyzer(text)
        insights_dict: dict | None = None
        if request.insights is not None:
            raw = request.insights.model_dump(exclude_none=True)
            insights_dict = raw if raw else None

        conv: list[dict[str, str]] | None = None
        if request.conversation:
            conv = [t.model_dump() for t in request.conversation]

        result = analyzer.answer_question(
            q,
            insights=insights_dict,
            conversation=conv,
        )
        return {
            "answer": result.text,
            "document_id": request.file_id,
            "analysis_source": result.source,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during Q&A for file_id=%s", request.file_id)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while answering your question.",
        )


# ---------------------------------------------------------------------------
# Export analysis (PDF / DOCX)
# ---------------------------------------------------------------------------


class ExportAnalysisRequest(BaseModel):
    document_name: str = "document"
    analyzed_at: str | None = None
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    entities: dict[str, list[str]] = Field(default_factory=dict)
    analysis_source: str | None = None


def _content_disposition_attachment(filename: str) -> str:
    ascii_fn = "".join(c if ord(c) < 128 and c not in '\"\\\\' else "_" for c in filename) or "export"
    return f'attachment; filename="{ascii_fn}"; filename*=UTF-8\'\'{quote(filename)}'


@router.post("/export/pdf")
async def export_analysis_pdf_endpoint(request: ExportAnalysisRequest) -> Response:
    try:
        content, filename = build_analysis_pdf(
            document_name=request.document_name,
            analyzed_at=request.analyzed_at or "",
            summary=request.summary,
            key_points=request.key_points,
            entities=request.entities,
            analysis_source=request.analysis_source,
        )
    except ImportError as exc:
        logger.exception("PDF export dependency missing or wrong package")
        raise HTTPException(
            status_code=503,
            detail=str(exc) or "PDF export is not available. Install fpdf2 in your environment.",
        ) from exc
    except Exception:
        logger.exception("PDF export failed")
        raise HTTPException(status_code=500, detail="Could not generate PDF export.") from None
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )


@router.post("/export/docx")
async def export_analysis_docx_endpoint(request: ExportAnalysisRequest) -> Response:
    try:
        content, filename = build_analysis_docx(
            document_name=request.document_name,
            analyzed_at=request.analyzed_at or "",
            summary=request.summary,
            key_points=request.key_points,
            entities=request.entities,
            analysis_source=request.analysis_source,
        )
    except Exception:
        logger.exception("DOCX export failed")
        raise HTTPException(status_code=500, detail="Could not generate DOCX export.") from None
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )
