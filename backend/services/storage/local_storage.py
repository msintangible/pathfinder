import logging
from pathlib import Path

from core.config import settings
from services.storage import ResumeStorage

logger = logging.getLogger(__name__)

# backend/ package root — services/storage/local_storage.py -> services/storage -> services -> backend
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

# Used when the configured path can't be created/written — e.g. resume_storage_path
# points at a production disk mount (/var/data/...) that isn't actually mounted.
# Always writable because it lives inside the deployed project tree. Ephemeral on
# hosts with no persistent disk: files here are lost on restart/redeploy, so this
# is a last-resort fallback, not a substitute for a real mounted disk.
_FALLBACK_PATH = _BACKEND_ROOT / "storage" / "resumes"


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
        configured_path = raw_path if raw_path.is_absolute() else _BACKEND_ROOT / raw_path
        self._base_path = self._ensure_writable_dir(configured_path)

    @staticmethod
    def _ensure_writable_dir(path: Path) -> Path:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError as exc:
            if path == _FALLBACK_PATH:
                raise
            logger.warning(
                "resume_storage_path %s is not usable (%s); falling back to %s. "
                "Files stored there are lost on restart — mount a persistent disk "
                "at that path to fix this.",
                path, exc, _FALLBACK_PATH,
            )
            _FALLBACK_PATH.mkdir(parents=True, exist_ok=True)
            return _FALLBACK_PATH

    def save(self, pdf_bytes: bytes, filename: str) -> str:
        path = self._base_path / filename
        path.write_bytes(pdf_bytes)
        return str(path)
