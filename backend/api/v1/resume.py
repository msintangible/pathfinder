import logging
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.rate_limit import generation_rate_limit
from core.security import get_current_user, get_current_user_allow_query_token
from database.session import get_db
from models.job import Job
from models.profile import UserProfile
from models.user import User
from schemas.jobs import JobResponse
from schemas.profile import CandidateProfile
from schemas.resume import GenerateResumeRequest, ResumeGenerationResponse
from services.llm_output import LLMOutputError
from services.repository.job_repository import JobRepository
from services.repository.profile_repository import ProfileRepository
from services.repository.resume_repository import ResumeRepository
from services.resume_generation_agent import ResumeGenerationAgent
from services.resume_page_fitter import render_within_page_limit
from services.resume_validator import validate_resume_structure
from services.storage.local_storage import LocalResumeStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resumes", tags=["resumes"])

# Media type per rendered_file_format — always "pdf" now that every resume is
# rendered via the generic Jinja2/xhtml2pdf template (see resume_renderer.py).
_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _profile_to_dict(profile: UserProfile) -> dict:
    return CandidateProfile.model_validate(profile, from_attributes=True).model_dump(mode="json")


def _job_to_dict(job: Job) -> dict:
    return JobResponse.model_validate(job, from_attributes=True).model_dump(mode="json")


def _render_resume(profile: UserProfile, result: dict) -> tuple[bytes, str, bool, dict]:
    """
    Renders optimized_resume via the generic Jinja2/xhtml2pdf template using
    its one fixed canonical section order (see resume_renderer.py).
    layout_preserved is always False since in-place rendering is no longer
    used — kept in the return shape because ResumeGenerationResponse/
    ResumeVersion still carry the field.

    Trims the lowest-relevance project/experience entry and re-renders if
    the result would exceed the 2-page budget (see resume_page_fitter.py),
    returning whichever resume was actually rendered so callers persist and
    display exactly what the PDF shows. Logs any structural completeness
    gaps (see resume_validator.py) without blocking generation on them —
    e.g. a candidate with no portfolio link is a real gap, not a bug to
    reject the resume over.
    """
    resume = result["optimized_resume"]
    for issue in validate_resume_structure(resume):
        logger.warning("profile %s: resume structure issue — %s", profile.id, issue)

    pdf_bytes, rendered_resume = render_within_page_limit(resume)
    return pdf_bytes, "pdf", False, rendered_resume


@router.post("/generate", response_model=ResumeGenerationResponse, dependencies=[Depends(generation_rate_limit)])
async def generate_resume(
    body: GenerateResumeRequest,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ResumeGenerationResponse:
    job_repo = JobRepository(session)
    profile_repo = ProfileRepository(session)

    job = await job_repo.get_by_id(body.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    profile = await profile_repo.get_by_id(body.user_profile_id)
    # Same 404 for "doesn't exist" and "isn't yours" — a 403 would confirm
    # to the caller that the guessed profile_id belongs to someone else.
    if profile is None or profile.user_id != user.id:
        raise HTTPException(status_code=404, detail="Profile not found")

    agent = ResumeGenerationAgent()
    profile_dict = _profile_to_dict(profile)
    try:
        result = await agent.generate(
            profile=profile_dict,
            job=_job_to_dict(job),
            layout_document=profile.layout_document,
        )
    except LLMOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    rendered_bytes, rendered_file_format, layout_preserved, rendered_resume = _render_resume(profile, result)

    storage = LocalResumeStorage()
    rendered_file_path = storage.save(rendered_bytes, f"{uuid.uuid4().hex}.{rendered_file_format}")

    resume_repo = ResumeRepository(session)
    resume = await resume_repo.create_from_generation(
        user_profile_id=body.user_profile_id,
        job_id=body.job_id,
        optimized_resume=rendered_resume,
        matched_keywords=result["matched_keywords"],
        missing_keywords=result["missing_keywords"],
        added_keywords=result["added_keywords"],
        ats_score=result["ats_score"],
        report=result["report"],
        rendered_file_url=rendered_file_path,
        rendered_file_format=rendered_file_format,
        layout_preserved=layout_preserved,
    )

    return ResumeGenerationResponse(
        ats_score=resume.ats_score,
        matched_keywords=resume.matched_keywords or [],
        missing_keywords=resume.missing_keywords or [],
        added_keywords=resume.added_keywords or [],
        optimized_resume=resume.content,
        report=resume.report,
        download_url=f"/v1/resumes/{resume.id}/download",
        layout_preserved=resume.layout_preserved,
    )


@router.get("/{resume_id}/download")
async def download_resume(
    resume_id: UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user_allow_query_token),
) -> FileResponse:
    resume = await ResumeRepository(session).get_by_id(resume_id)
    if resume is None or not resume.rendered_file_url:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Ownership is derived through the linked profile — ResumeVersion has no
    # user_id of its own, see resume_versions.user_profile_id.
    profile = await ProfileRepository(session).get_by_id(resume.user_profile_id)
    if profile is None or profile.user_id != user.id:
        raise HTTPException(status_code=404, detail="Resume not found")

    file_format = resume.rendered_file_format or "pdf"
    return FileResponse(
        resume.rendered_file_url,
        media_type=_MEDIA_TYPES.get(file_format, "application/octet-stream"),
        filename=f"resume-{resume_id}.{file_format}",
    )
