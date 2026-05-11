import logging
import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

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

        # --- Analyse (Israa's class / mock until her module is ready) ---
        analyzer = DocumentAnalyzer(text)
        return {
            "summary": analyzer.summary(),
            "key_points": analyzer.key_points(),
            "entities": analyzer.entities(),
            "document_id": request.file_id,
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
