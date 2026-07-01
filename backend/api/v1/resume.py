import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from models.job import Job
from models.profile import UserProfile
from schemas.jobs import JobResponse
from schemas.profile import CandidateProfile
from schemas.resume import GenerateResumeRequest, ResumeGenerationResponse
from services.repository.job_repository import JobRepository
from services.repository.profile_repository import ProfileRepository
from services.repository.resume_repository import ResumeRepository
from services.resume_generation_agent import ResumeGenerationAgent
from services.resume_renderer import render_pdf
from services.storage.local_storage import LocalResumeStorage

router = APIRouter(prefix="/resumes", tags=["resumes"])


def _profile_to_dict(profile: UserProfile) -> dict:
    return CandidateProfile.model_validate(profile, from_attributes=True).model_dump(mode="json")


def _job_to_dict(job: Job) -> dict:
    return JobResponse.model_validate(job, from_attributes=True).model_dump(mode="json")


@router.post("/generate", response_model=ResumeGenerationResponse)
async def generate_resume(
    body: GenerateResumeRequest,
    session: AsyncSession = Depends(get_db),
) -> ResumeGenerationResponse:
    job_repo = JobRepository(session)
    profile_repo = ProfileRepository(session)

    job = await job_repo.get_by_id(body.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    profile = await profile_repo.get_by_id(body.user_profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    agent = ResumeGenerationAgent()
    result = await agent.generate(
        profile=_profile_to_dict(profile),
        job=_job_to_dict(job),
    )

    pdf_bytes = render_pdf(result["optimized_resume"])
    storage = LocalResumeStorage()
    rendered_pdf_path = storage.save(pdf_bytes, f"{uuid.uuid4().hex}.pdf")

    resume_repo = ResumeRepository(session)
    resume = await resume_repo.create_from_generation(
        user_profile_id=body.user_profile_id,
        job_id=body.job_id,
        optimized_resume=result["optimized_resume"],
        matched_keywords=result["matched_keywords"],
        missing_keywords=result["missing_keywords"],
        ats_score=result["ats_score"],
        rendered_pdf_url=rendered_pdf_path,
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
) -> FileResponse:
    resume = await ResumeRepository(session).get_by_id(resume_id)
    if resume is None or not resume.rendered_pdf_url:
        raise HTTPException(status_code=404, detail="Resume not found")

    return FileResponse(
        resume.rendered_pdf_url,
        media_type="application/pdf",
        filename=f"resume-{resume_id}.pdf",
    )
