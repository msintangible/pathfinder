
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.jobs import AnalyzeJobRequest, JobResponse
from database.session import get_db
from services.job_analysis_agent import JobAnalysisAgent
from services.repository.job_repository import JobRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/analyze", response_model=JobResponse)
async def analyze_job(
    body: AnalyzeJobRequest,
    session: AsyncSession = Depends(get_db),
) -> JobResponse:
    agent = JobAnalysisAgent()
    analysis = await agent.analyze(raw_text=body.raw_text, url=body.url)

    repo = JobRepository(session)
    job = await repo.create_from_analysis(
        raw_text=body.raw_text,
        analysis=analysis,
        url=body.url,
    )
    return JobResponse.model_validate(job)
