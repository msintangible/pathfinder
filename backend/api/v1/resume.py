import uuid
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from database.session import get_db
from models.job import Job
from models.profile import UserProfile
from models.user import User
from schemas.jobs import JobResponse
from schemas.profile import CandidateProfile
from schemas.resume import GenerateResumeRequest, ResumeGenerationResponse
from services.docx_resume_renderer import render_docx
from services.llm_output import LLMOutputError
from services.repository.job_repository import JobRepository
from services.repository.profile_repository import ProfileRepository
from services.repository.resume_repository import ResumeRepository
from services.resume_generation_agent import ResumeGenerationAgent
from services.resume_renderer import render_pdf
from services.storage.local_storage import LocalResumeStorage

router = APIRouter(prefix="/resumes", tags=["resumes"])

# Media type per rendered_file_format — docx-sourced profiles get their
# original file edited in place (see docx_resume_renderer.py); everyone else
# gets the generic Jinja2-rendered PDF (see resume_renderer.py).
_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _profile_to_dict(profile: UserProfile) -> dict:
    return CandidateProfile.model_validate(profile, from_attributes=True).model_dump(mode="json")


def _job_to_dict(job: Job) -> dict:
    return JobResponse.model_validate(job, from_attributes=True).model_dump(mode="json")


@router.post("/generate", response_model=ResumeGenerationResponse)
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
        )
    except LLMOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if profile.source_document_format == "docx" and profile.source_document_path:
        source_bytes = Path(profile.source_document_path).read_bytes()
        rendered_bytes = render_docx(source_bytes, profile_dict, result["optimized_resume"])
        rendered_file_format = "docx"
    else:
        rendered_bytes = render_pdf(result["optimized_resume"])
        rendered_file_format = "pdf"

    storage = LocalResumeStorage()
    rendered_file_path = storage.save(rendered_bytes, f"{uuid.uuid4().hex}.{rendered_file_format}")

    resume_repo = ResumeRepository(session)
    resume = await resume_repo.create_from_generation(
        user_profile_id=body.user_profile_id,
        job_id=body.job_id,
        optimized_resume=result["optimized_resume"],
        matched_keywords=result["matched_keywords"],
        missing_keywords=result["missing_keywords"],
        ats_score=result["ats_score"],
        rendered_file_url=rendered_file_path,
        rendered_file_format=rendered_file_format,
    )

    return ResumeGenerationResponse(
        ats_score=resume.ats_score,
        matched_keywords=resume.matched_keywords or [],
        missing_keywords=resume.missing_keywords or [],
        optimized_resume=resume.content,
        download_url=f"/v1/resumes/{resume.id}/download",
    )


@router.get("/{resume_id}/download")
async def download_resume(
    resume_id: UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
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
