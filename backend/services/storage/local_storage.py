from pathlib import Path

from core.config import settings
from services.storage import ResumeStorage

# backend/ package root — services/storage/local_storage.py -> services/storage -> services -> backend
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class LocalResumeStorage(ResumeStorage):
    """Writes rendered PDFs to a local directory. Returns the filesystem path, not a public URL — the API layer builds the public download link."""

    def __init__(self, base_path: str | None = None) -> None:
        raw_path = Path(base_path or settings.resume_storage_path)
        # A relative path (e.g. the "./storage/resumes" default) must not
        # resolve against the process's CWD — that varies by how the server
        # is launched and has already caused files to scatter across two
        # different real directories. Anchor it to backend/ instead. An
        # absolute path (e.g. a mounted production disk) passes through
        # unchanged.
        self._base_path = raw_path if raw_path.is_absolute() else _BACKEND_ROOT / raw_path
        self._base_path.mkdir(parents=True, exist_ok=True)

    def save(self, pdf_bytes: bytes, filename: str) -> str:
        path = self._base_path / filename
        path.write_bytes(pdf_bytes)
        return str(path)
