from pathlib import Path

from core.config import settings
from services.storage import ResumeStorage


class LocalResumeStorage(ResumeStorage):
    """Writes rendered PDFs to a local directory. Returns the filesystem path, not a public URL — the API layer builds the public download link."""

    def __init__(self, base_path: str | None = None) -> None:
        self._base_path = Path(base_path or settings.resume_storage_path)
        self._base_path.mkdir(parents=True, exist_ok=True)

    def save(self, pdf_bytes: bytes, filename: str) -> str:
        path = self._base_path / filename
        path.write_bytes(pdf_bytes)
        return str(path)
