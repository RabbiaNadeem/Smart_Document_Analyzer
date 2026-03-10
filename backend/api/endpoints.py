import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.services.supabase_service import upload_to_storage

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
    # --- Extension check ---
    ext = os.path.splitext(file.filename or "")[1].lower()
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

    # --- Magic-byte validation for binary formats ---
    if ext in _MAGIC_BYTES:
        if not file_bytes.startswith(_MAGIC_BYTES[ext]):
            raise HTTPException(
                status_code=400,
                detail=f"File content does not match the expected binary signature for {ext}.",
            )

    # --- Upload to Firebase Storage ---
    file_id = str(uuid.uuid4())
    destination_path = f"uploads/{file_id}{ext}"

    upload_to_storage(file_bytes, destination_path, file.content_type)

    return {"file_id": file_id, "message": "Upload successful"}