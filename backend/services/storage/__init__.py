from abc import ABC, abstractmethod


class ResumeStorage(ABC):
    """Storage boundary for rendered resume PDFs — swap the implementation (e.g. for S3) without touching the generation pipeline."""

    @abstractmethod
    def save(self, pdf_bytes: bytes, filename: str) -> str:
        """Persist the PDF and return a URL the client can download it from."""
