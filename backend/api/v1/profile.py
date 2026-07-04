import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from database.session import get_db
from models.user import User
from schemas.profile import (
    CandidateProfile,
    CandidateProfileInput,
    ProfileImportResponse,
    ProfileRestoreRequest,
    ProfileRestoreResponse,
)
from services.candidate_profile_agent import CandidateProfileAgent
from services.docx_layout_extractor import DocxLayoutExtractionError, extract_docx_layout
from services.docx_text_extractor import DocxExtractionError, extract_docx_text
from services.gemini_vision_layout_agent import GeminiVisionLayoutAgent
from services.github_profile_fetcher import fetch_github_profile
from services.llm_output import LLMOutputError
from services.pdf_layout_extractor import PdfLayoutExtractionError, extract_pdf_layout
from services.pdf_text_extractor import PDFExtractionError, extract_pdf_text
from services.portfolio_scraper import fetch_portfolio_text
from services.repository.profile_repository import ProfileRepository
from services.storage.local_storage import LocalResumeStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])

# Mirrors extension/src/shared/constants.js's Upload.MAX_BYTES — enforced
# server-side too since client-side validation can't be trusted.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _is_pdf(file: UploadFile) -> bool:
    return file.content_type == "application/pdf" or (file.filename or "").lower().endswith(".pdf")


def _is_docx(file: UploadFile) -> bool:
    return file.content_type == _DOCX_CONTENT_TYPE or (file.filename or "").lower().endswith(".docx")


def _save_source_document(file_bytes: bytes, extension: str) -> str:
    return LocalResumeStorage().save(file_bytes, f"source-{uuid.uuid4().hex}.{extension}")


def _try_build_docx_layout(file_bytes: bytes) -> dict | None:
    try:
        return extract_docx_layout(file_bytes).model_dump()
    except DocxLayoutExtractionError:
        logger.warning("Could not build a docx layout document for this upload; falling back to text-only.")
        return None


async def _try_build_pdf_layout(file_bytes: bytes) -> dict | None:
    try:
        layout = extract_pdf_layout(file_bytes)
    except PdfLayoutExtractionError:
        logger.warning("Could not build a pdf layout document for this upload; falling back to text-only.")
        return None

    try:
        layout = await GeminiVisionLayoutAgent().label_document(file_bytes, layout)
    except Exception:
        # Vision labeling only adds section-role metadata (used by the Patch
        # Engine's skills-section handling) on top of the already-usable
        # deterministic extraction above — a Gemini outage/quota error here
        # must not block profile import over a best-effort enhancement.
        logger.warning("Vision layout labeling failed; using unlabeled PDF layout.", exc_info=True)

    return layout.model_dump()


@router.post("/import", response_model=ProfileImportResponse)
async def import_profile(
    file: UploadFile | None = None,
    linkedin_url: Annotated[HttpUrl | None, Form()] = None,
    linkedin_text: str | None = Form(None),
    github_url: Annotated[HttpUrl | None, Form()] = None,
    portfolio_url: Annotated[HttpUrl | None, Form()] = None,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfileImportResponse:
    # FastAPI/Pydantic already rejected malformed/non-http(s) URLs with a 422
    # before this line; everything below (regex parsing, the SSRF-guarded
    # fetch, the Text DB columns) expects plain strings, so normalize once.
    linkedin_url = str(linkedin_url) if linkedin_url else None
    github_url = str(github_url) if github_url else None
    portfolio_url = str(portfolio_url) if portfolio_url else None

    resume_text: str | None = None
    source_document_path: str | None = None
    source_document_format: str | None = None
    layout_document: dict | None = None

    if file is not None:
        is_docx = _is_docx(file)
        if not _is_pdf(file) and not is_docx:
            raise HTTPException(status_code=400, detail="Only PDF or DOCX files are supported.")

        file_bytes = await file.read()
        if len(file_bytes) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File exceeds the 10MB limit.")

        if is_docx:
            try:
                resume_text = extract_docx_text(file_bytes) or None
            except DocxExtractionError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            # Stored so resume generation can edit this file in place later
            # (preserving its real layout) instead of rendering a generic
            # template — see docx_renderer_v2.py.
            source_document_path = _save_source_document(file_bytes, "docx")
            source_document_format = "docx"
            layout_document = _try_build_docx_layout(file_bytes)
        else:
            try:
                resume_text = extract_pdf_text(file_bytes) or None
            except PDFExtractionError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            # Stored so resume generation can edit this file in place later —
            # see pdf_renderer_v2.py.
            source_document_path = _save_source_document(file_bytes, "pdf")
            source_document_format = "pdf"
            layout_document = await _try_build_pdf_layout(file_bytes)

    if not resume_text and not (linkedin_url or github_url or portfolio_url):
        raise HTTPException(status_code=400, detail="Provide a CV file or at least one profile URL.")

    (github_profile_text, github_repos), portfolio_text = await asyncio.gather(
        fetch_github_profile(github_url),
        fetch_portfolio_text(portfolio_url),
    )

    # A blank prompt makes the model fabricate a profile instead of returning
    # nulls, despite the "never invent" system instruction — e.g. a mistyped
    # GitHub username with no other source would otherwise persist a fake
    # identity. Refuse rather than call the agent with nothing to analyze.
    if not (resume_text or linkedin_text or github_profile_text or github_repos or portfolio_text):
        raise HTTPException(
            status_code=422,
            detail="Couldn't extract any usable content from the provided sources. "
                   "Check the URLs, or provide a CV.",
        )

    sources = CandidateProfileInput(
        resume_text=resume_text,
        linkedin_text=linkedin_text or None,
        github_profile=github_profile_text,
        github_repositories=github_repos,
        portfolio_text=portfolio_text,
    )

    agent = CandidateProfileAgent()
    try:
        analysis = await agent.analyze(sources)
    except LLMOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    repo = ProfileRepository(session)
    profile = await repo.create_from_analysis(
        analysis,
        user_id=user.id,
        linkedin_url=linkedin_url,
        github_url=github_url,
        portfolio_url=portfolio_url,
        source_document_path=source_document_path,
        source_document_format=source_document_format,
        layout_document=layout_document,
    )

    return ProfileImportResponse(
        id=profile.id,
        profile=CandidateProfile.model_validate(profile, from_attributes=True),
        sources=sources,
    )


@router.post("/restore", response_model=ProfileRestoreResponse)
async def restore_profile(
    body: ProfileRestoreRequest,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfileRestoreResponse:
    # No LLM call — the client is handing back data we already analyzed once.
    # linkedin_url/github_url/portfolio_url and any docx source_document_path
    # aren't part of CandidateProfile, so they come back null; only the
    # analyzed fields are recoverable this way.
    repo = ProfileRepository(session)
    profile = await repo.create_from_analysis(
        body.profile.model_dump(mode="json"),
        user_id=user.id,
    )
    return ProfileRestoreResponse(
        id=profile.id,
        profile=CandidateProfile.model_validate(profile, from_attributes=True),
    )
