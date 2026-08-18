
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import get_current_user
from schemas.jobs import AnalyzeJobRequest, JobResponse
from database.session import get_db
from models.user import User
from services.job_analysis_agent import JobAnalysisAgent
from services.llm_output import LLMOutputError
from services.repository.gemini_usage_repository import GeminiDailyLimitExceeded, GeminiUsageRepository
from services.repository.job_repository import JobRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/analyze", response_model=JobResponse)
async def analyze_job(
    body: AnalyzeJobRequest,
    session: AsyncSession = Depends(get_db),
    # Jobs are deduped/shared across all users (see posting_text_hash), so
    # this only requires the caller to be authenticated — no ownership.
    _user: User = Depends(get_current_user),
) -> JobResponse:
    # Pydantic already validated body.url as an HttpUrl; downstream (the
    # agent and the Text DB column) both expect a plain string.
    url = str(body.url) if body.url else None

    agent = JobAnalysisAgent()
    try:
        await GeminiUsageRepository(session).increment_and_check(settings.gemini_daily_call_limit)
        analysis = await agent.analyze(raw_text=body.raw_text, url=url)
    except LLMOutputError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except GeminiDailyLimitExceeded as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    repo = JobRepository(session)
    job = await repo.create_from_analysis(
        raw_text=body.raw_text,
        analysis=analysis,
        url=url,
    )
    return JobResponse.model_validate(job)
