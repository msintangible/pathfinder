import asyncio

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from schemas.profile import CandidateProfile, CandidateProfileInput, ProfileImportResponse
from services.candidate_profile_agent import CandidateProfileAgent
from services.github_profile_fetcher import fetch_github_profile
from services.pdf_text_extractor import PDFExtractionError, extract_pdf_text
from services.portfolio_scraper import fetch_portfolio_text
from services.repository.profile_repository import ProfileRepository

router = APIRouter(prefix="/profile", tags=["profile"])

# Mirrors extension/src/shared/constants.js's Upload.MAX_BYTES — enforced
# server-side too since client-side validation can't be trusted.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _is_pdf(file: UploadFile) -> bool:
    return file.content_type == "application/pdf" or (file.filename or "").lower().endswith(".pdf")


@router.post("/import", response_model=ProfileImportResponse)
async def import_profile(
    file: UploadFile | None = None,
    linkedin_url: str | None = Form(None),
    linkedin_text: str | None = Form(None),
    github_url: str | None = Form(None),
    portfolio_url: str | None = Form(None),
    session: AsyncSession = Depends(get_db),
) -> ProfileImportResponse:
    resume_text: str | None = None

    if file is not None:
        if not _is_pdf(file):
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")

        pdf_bytes = await file.read()
        if len(pdf_bytes) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File exceeds the 10MB limit.")

        try:
            resume_text = extract_pdf_text(pdf_bytes) or None
        except PDFExtractionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    agent = CandidateProfileAgent()
    analysis = await agent.analyze(
        CandidateProfileInput(
            resume_text=resume_text,
            linkedin_text=linkedin_text or None,
            github_profile=github_profile_text,
            github_repositories=github_repos,
            portfolio_text=portfolio_text,
        )
    )

    repo = ProfileRepository(session)
    profile = await repo.create_from_analysis(
        analysis,
        linkedin_url=linkedin_url,
        github_url=github_url,
        portfolio_url=portfolio_url,
    )

    return ProfileImportResponse(
        profile=CandidateProfile.model_validate(profile, from_attributes=True)
    )
