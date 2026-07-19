import logging
import uuid
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user, get_current_user_allow_query_token
from database.session import get_db
from models.job import Job
from models.profile import UserProfile
from models.user import User
from schemas.jobs import JobResponse
from schemas.profile import CandidateProfile
from schemas.resume import GenerateResumeRequest, ResumeGenerationResponse
from schemas.resume_layout import ResumeLayoutDocument
from services.docx_renderer_v2 import render_docx
from services.llm_output import LLMOutputError
from services.pdf_renderer_v2 import render_pdf as render_pdf_in_place
from services.repository.job_repository import JobRepository
from services.repository.profile_repository import ProfileRepository
from services.repository.resume_repository import ResumeRepository
from services.resume_generation_agent import ResumeGenerationAgent
from services.resume_renderer import render_pdf as render_pdf_template
from services.resume_section_order import infer_section_order
from services.storage.local_storage import LocalResumeStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resumes", tags=["resumes"])

# Media type per rendered_file_format — a source document (docx or pdf) edited
# in place (see docx_renderer_v2.py / pdf_renderer_v2.py) when layout_preserved
# is True; the generic Jinja2-rendered PDF (see resume_renderer.py) otherwise.
_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# TEMP DEBUG FLAG — set back to False to restore in-place rendering.
_DEBUG_FORCE_TEMPLATE_RENDER = True


def _profile_to_dict(profile: UserProfile) -> dict:
    return CandidateProfile.model_validate(profile, from_attributes=True).model_dump(mode="json")


def _job_to_dict(job: Job) -> dict:
    return JobResponse.model_validate(job, from_attributes=True).model_dump(mode="json")


def _render_resume(profile: UserProfile, result: dict) -> tuple[bytes, str, bool]:
    """
    Renders the candidate's actual uploaded file in place when the agent
    produced a confidently-correlated render_layout (see
    ResumeGenerationAgent._build_render_layout); otherwise falls back to the
    generic Jinja2/xhtml2pdf template, unconditionally rendered from
    optimized_resume so a low-confidence or missing correlation never blocks
    generation, it only loses layout preservation for this run. The fallback
    still uses profile.layout_document's inferred section order (see
    resume_section_order.py) even when it can't preserve real formatting.
    """
    # TEMP DEBUG: force the generic template renderer, bypassing in-place
    # rendering entirely. Flip back to False when done comparing.
    if _DEBUG_FORCE_TEMPLATE_RENDER:
        section_order = infer_section_order(profile.layout_document)
        return render_pdf_template(result["optimized_resume"], section_order=section_order), "pdf", False

    if result["layout_preserved"] and profile.source_document_path:
        source_bytes = Path(profile.source_document_path).read_bytes()
        render_layout = ResumeLayoutDocument.model_validate(result["render_layout"])

        if profile.source_document_format == "docx":
            logger.info("profile %s: rendering in place via docx_renderer_v2", profile.id)
            return render_docx(source_bytes, render_layout), "docx", True

        if profile.source_document_format == "pdf":
            logger.info("profile %s: rendering in place via pdf_renderer_v2", profile.id)
            pdf_result = render_pdf_in_place(source_bytes, render_layout)
            if pdf_result.low_confidence_block_ids:
                logger.info(
                    "profile %s: %d block(s) rendered with a substituted font or truncated text: %s",
                    profile.id, len(pdf_result.low_confidence_block_ids), pdf_result.low_confidence_block_ids,
                )
            return pdf_result.pdf_bytes, "pdf", True

        logger.warning(
            "profile %s: layout_preserved=True but source_document_format=%r is neither docx nor pdf — falling back",
            profile.id, profile.source_document_format,
        )
    elif not profile.source_document_path:
        logger.info("profile %s: no source document — falling back to the generic template", profile.id)
    else:
        logger.info("profile %s: layout correlation wasn't confident enough this run — falling back", profile.id)

    section_order = infer_section_order(profile.layout_document)
    return render_pdf_template(result["optimized_resume"], section_order=section_order), "pdf", False


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
            layout_document=profile.layout_document,
        )
    except LLMOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    rendered_bytes, rendered_file_format, layout_preserved = _render_resume(profile, result)

    storage = LocalResumeStorage()
    rendered_file_path = storage.save(rendered_bytes, f"{uuid.uuid4().hex}.{rendered_file_format}")

    resume_repo = ResumeRepository(session)
    resume = await resume_repo.create_from_generation(
        user_profile_id=body.user_profile_id,
        job_id=body.job_id,
        optimized_resume=result["optimized_resume"],
        matched_keywords=result["matched_keywords"],
        missing_keywords=result["missing_keywords"],
        added_keywords=result["added_keywords"],
        ats_score=result["ats_score"],
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
