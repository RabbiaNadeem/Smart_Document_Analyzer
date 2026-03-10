# Document Analyzer

A web application for uploading and analyzing documents. Extract readable text from PDF, DOCX, TXT, and CSV files for AI processing.

## Features

- **File Upload**: Secure upload of PDF, DOCX, TXT, and CSV files with validation
- **Text Extraction**: Automatic extraction of readable text from uploaded documents
- **Storage**: Files stored in Supabase Storage with public URLs
- **Web Interface**: Drag-and-drop file upload with progress tracking
- **API**: RESTful API built with FastAPI

## Supported File Types

- **PDF**: Text extraction using PyPDF2
- **DOCX**: Text extraction using python-docx
- **TXT**: Plain text reading
- **CSV**: Structured data parsing with pandas

## Setup

### Prerequisites

- Python 3.8+
- Supabase account (for storage)

### Installation

1. Clone the repository:
   ```bash
   git clone <your-repo-url>
   cd document_analyzer
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up Supabase:
   - Create a new Supabase project
   - Create a storage bucket (e.g., "documents")
   - Get your project URL and service role key

5. Configure environment variables:
   Create a `.env` file in the root directory:
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_KEY=your-service-role-key
   SUPABASE_BUCKET=documents
   ```

### Running the Application

1. Start the server:
   ```bash
   uvicorn main:app --reload
   ```

2. Open your browser to `http://localhost:8000`

3. Upload files via the web interface or API at `http://localhost:8000/api/upload`

## API Usage

### Upload Endpoint

**POST** `/api/upload`

Upload a file and get extracted text in response.

**Request:**
- Content-Type: `multipart/form-data`
- Body: `file` (the document to upload)

**Response:**
```json
{
  "file_id": "uuid-string",
  "message": "Upload successful",
  "extracted_text": "Extracted text content..."
}
```

**Supported file types:** PDF, DOCX, TXT, CSV (max 10MB)

## Testing

Run the test suite:
```bash
pytest tests/
```

## Project Structure

```
document_analyzer/
├── main.py                 # FastAPI app entry point
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not committed)
├── .gitignore              # Git ignore rules
├── static/
│   └── index.html          # Frontend UI
├── backend/
│   ├── api/
│   │   ├── __init__.py
│   │   └── endpoints.py    # API endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   ├── supabase_service.py  # Storage service
│   │   └── document_processor.py # Text extraction
│   └── utils/
│       └── __init__.py
└── tests/
    ├── test_document_processor.py
    └── sample_files/       # Test files
```

## Security

- File type validation with MIME type and magic byte checks
- File size limits (10MB max)
- Environment variables for sensitive configuration
- No secrets committed to version control

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License