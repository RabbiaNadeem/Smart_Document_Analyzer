# Document Analyzer

A FastAPI web service for uploading documents, extracting their text, and producing
AI-powered analyses (summary, key points, named entities). Files are persisted to
Supabase Storage; analysis runs on demand against the previously uploaded file.

---

## Features

- **Two-step pipeline** — upload first, analyze on demand (no work wasted if the
  client never asks for analysis).
- **Multi-format ingestion** — PDF, DOCX, TXT, and CSV.
- **Hardened upload validation** — extension, MIME type, magic-byte signature,
  size cap, and empty-file guard.
- **Cloud storage** — files stored in Supabase Storage under
  `uploads/{file_id}{ext}`.
- **Drag-and-drop web UI** at `/`.
- **RESTful API** mounted under `/api`.

## Supported file types

| Type | Extension | Extractor               |
|------|-----------|-------------------------|
| PDF  | `.pdf`    | `PyPDF2`                |
| Word | `.docx`   | `python-docx`           |
| Text | `.txt`    | UTF-8 decode            |
| CSV  | `.csv`    | `pandas` (header + rows)|

Maximum upload size: **10 MB**.

---

## Setup

### Prerequisites

- Python 3.10+ (uses `X | Y` type-union syntax)
- A Supabase project with a Storage bucket

### Installation

```bash
git clone <your-repo-url>
cd document_analyzer

python -m venv venv
# Windows PowerShell
venv\Scripts\Activate.ps1
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### Configure Supabase

1. Create a Supabase project at <https://supabase.com>.
2. Create a Storage bucket (default name expected by this app: `documents`).
3. Copy your project URL and **service role** key from
   *Project Settings → API*.

### Environment variables

Create a `.env` file in the project root:

```env
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_SERVICE_KEY=<your-service-role-key>
SUPABASE_BUCKET=documents
GEMINI_API_KEY=<your-google-ai-studio-api-key>
# Optional: GEMINI_MODEL=gemini-2.5-flash
```

> The service key is privileged — never commit it. `.env` is already gitignored.
> Set `GEMINI_API_KEY` for Gemini-powered summaries, entities, and Q&A; if it is
> missing, the app uses a local heuristic fallback (see `backend/services/ai_analyzer.py`).

---

## Running the application

**Always run from the project root** (`document_analyzer/`), not from inside the
`backend/` folder — otherwise uvicorn cannot import `main` and the inner
`from backend.api.endpoints import router` will also fail:

```bash
# From the project root
uvicorn main:app --reload
```

Then open <http://localhost:8000>.

Equivalent alternatives if you prefer not to `cd`:

```bash
python -m uvicorn main:app --reload
# or, from anywhere:
uvicorn --app-dir /absolute/path/to/document_analyzer main:app --reload
```

---

## API reference

All endpoints are mounted under the `/api` prefix.

### `POST /api/upload`

Validate and persist a document. Returns a `file_id` you can pass to
`/api/analyze` later.

**Request**

- `Content-Type: multipart/form-data`
- Field: `file` — the document to upload

**Success response — `200 OK`**

```json
{
  "file_id": "f7d3a8e2-9c11-4b6d-9a87-1c4f2e6b8a31",
  "file_ext": ".pdf",
  "message": "Upload successful"
}
```

**Error responses**

| Status | When |
|-------:|------|
| `400`  | Missing filename, unsupported extension, unsupported MIME type, magic-byte mismatch, or empty file |
| `413`  | File exceeds the 10 MB limit |
| `502`  | Supabase Storage upload failed |

**Example**

```bash
curl -F "file=@./report.pdf" http://localhost:8000/api/upload
```

---

### `POST /api/analyze`

Run analysis against a previously uploaded file.

**Request**

- `Content-Type: application/json`

```json
{
  "file_id": "f7d3a8e2-9c11-4b6d-9a87-1c4f2e6b8a31",
  "file_ext": ".pdf"
}
```

**Success response — `200 OK`**

```json
{
  "summary": "Executive summary paragraph…",
  "key_points": ["…", "…"],
  "entities": {
    "monetary_values": ["$150,000 (budget)"],
    "dates": ["Q2 2026"],
    "organizations": ["Example Corp"],
    "key_metrics": ["3.5x ROI"]
  },
  "document_id": "f7d3a8e2-9c11-4b6d-9a87-1c4f2e6b8a31",
  "analysis_source": "gemini",
  "extracted_text_preview": "…",
  "extracted_text_truncated": false,
  "extracted_text_length": 1200
}
```

> Analysis is produced by Google Gemini when `GEMINI_API_KEY` is set; otherwise
> the service returns a heuristic fallback. Implementation:
> [`backend/services/ai_analyzer.py`](backend/services/ai_analyzer.py) and
> [`backend/services/document_analyzer.py`](backend/services/document_analyzer.py).

**Error responses**

| Status | When |
|-------:|------|
| `400`  | Invalid `file_ext` value |
| `404`  | No file found for the given `file_id` in storage |
| `422`  | File downloaded but text extraction failed (corrupt / unsupported content) |
| `500`  | Unexpected server-side failure |

**Example**

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"file_id":"f7d3a8e2-9c11-4b6d-9a87-1c4f2e6b8a31","file_ext":".pdf"}'
```

---

### `POST /api/ask`

Answer a natural-language question using the uploaded document. The model is instructed to ground facts in the document text.

Optional **`insights`** (from `POST /api/analyze`) and **`conversation`** (prior Q&A turns) help with follow-ups—e.g. “expand on point 2”, “what you said about the budget”—while still requiring support from the document when stating facts.

**Request** (`application/json`)

```json
{
  "file_id": "f7d3a8e2-9c11-4b6d-9a87-1c4f2e6b8a31",
  "file_ext": ".pdf",
  "question": "What is the total budget?",
  "insights": {
    "summary": "…",
    "key_points": ["…", "…"],
    "entities": { "monetary_values": [], "dates": [], "organizations": [], "key_metrics": [] }
  },
  "conversation": [
    { "question": "Who is the client?", "answer": "…" }
  ]
}
```

`insights` and `conversation` may be omitted. The web UI sends them automatically after analysis and accumulates `conversation` across turns (last 10 on the server).

**Success — `200 OK`**

```json
{
  "answer": "…",
  "document_id": "f7d3a8e2-9c11-4b6d-9a87-1c4f2e6b8a31",
  "analysis_source": "gemini"
}
```

`analysis_source` here reflects **this answer** (`gemini` or `fallback`), not a re-run of full document analysis.

| Status | When |
|-------:|------|
| `400`  | Empty question or invalid `file_ext` |
| `404`  | File not in storage |
| `422`  | Text extraction failed |

---

## Project structure

```
document_analyzer/
├── main.py                       # FastAPI app entry point
├── requirements.txt              # Python dependencies
├── .env                          # Secrets (gitignored)
├── .env.example                  # Template for .env
├── .gitignore
├── README.md
├── static/
│   └── index.html                # Drag-and-drop UI
├── backend/
│   ├── api/
│   │   └── endpoints.py          # /api/upload, /api/analyze, /api/ask
│   ├── services/
│   │   ├── supabase_service.py   # Upload / download to Supabase Storage
│   │   ├── document_processor.py # Text extraction (path + bytes APIs)
│   │   ├── ai_analyzer.py        # Gemini prompts + JSON + fallbacks
│   │   └── document_analyzer.py  # Facade over ai_analyzer (cached full run)
│   └── utils/
└── tests/
    ├── test_document_processor.py
    ├── test_analyzer.py
    ├── sample_docs/              # e.g. marketing_proposal.txt
    └── sample_files/             # sample.pdf / .docx / .txt / .csv
```

---

## Validation pipeline (upload)

The upload endpoint applies validations in this order — the request is rejected
the moment any check fails, so no oversized or untrusted bytes are persisted:

1. **Filename present?** → `400` if missing.
2. **Extension allow-listed?** (`.pdf`, `.docx`, `.txt`, `.csv`) → `400`.
3. **MIME type allow-listed?** → `400`.
4. **Streamed read with 10 MB cap** (64 KB chunks) → `413` on overflow.
5. **Empty-file guard** → `400` if 0 bytes.
6. **Magic-byte signature** for binary formats:
   - PDF must start with `%PDF`
   - DOCX must start with `PK\x03\x04` (ZIP signature)
   → `400` on mismatch.
7. **Persist to Supabase Storage** at `uploads/{file_id}{ext}` → `502` on failure.
8. **Return** `{ file_id, file_ext, message }`.

---

## Testing

```bash
pytest tests/
```

Sample fixtures live in `tests/sample_files/` and cover all four supported
formats.

---

## Security notes

- File-type allow-listing with three independent layers (extension + MIME +
  magic bytes) to defeat naïve content-type spoofing.
- Hard 10 MB size cap, enforced *during* streaming so the server never
  buffers oversized payloads.
- Empty-file guard to avoid storing useless 0-byte objects.
- All secrets driven by environment variables; `.env` is gitignored.
- Supabase service key is used server-side only — never expose it to the
  browser.

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes and add tests
4. Run `pytest tests/`
5. Open a pull request

## License

MIT License
