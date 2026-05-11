import os

from supabase import Client, create_client

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Environment variables SUPABASE_URL and SUPABASE_SERVICE_KEY must be set."
        )

    _client = create_client(url, key)
    return _client


def upload_to_storage(file_bytes: bytes, destination_path: str, content_type: str) -> str:
    """Upload bytes to Supabase Storage and return the public URL."""
    bucket = os.getenv("SUPABASE_BUCKET", "documents")
    client = _get_client()

    client.storage.from_(bucket).upload(
        path=destination_path,
        file=file_bytes,
        file_options={"content-type": content_type, "upsert": "false"},
    )

    public_url: str = client.storage.from_(bucket).get_public_url(destination_path)
    return public_url


def download_from_storage(file_id: str, ext: str) -> bytes:
    """Download a previously uploaded file from Supabase Storage.

    Args:
        file_id: The UUID returned at upload time.
        ext:     File extension including the leading dot (e.g. ``".pdf"``).

    Returns:
        Raw file bytes.

    Raises:
        FileNotFoundError: If the object does not exist in the bucket.
    """
    bucket = os.getenv("SUPABASE_BUCKET", "documents")
    client = _get_client()
    path = f"uploads/{file_id}{ext}"

    try:
        data: bytes = client.storage.from_(bucket).download(path)
    except Exception as exc:
        raise FileNotFoundError(
            f"File '{path}' not found in storage bucket '{bucket}'."
        ) from exc

    return data
