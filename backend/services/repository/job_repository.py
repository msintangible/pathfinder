import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.job import Job


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _compute_hash(text: str) -> str:
        normalized = " ".join(text.split()).lower()
        return hashlib.sha256(normalized.encode()).hexdigest()

    async def get_by_hash(self, text_hash: str) -> Job | None:
        result = await self._session.execute(
            select(Job).where(Job.posting_text_hash == text_hash)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, job_id: uuid.UUID) -> Job | None:
        return await self._session.get(Job, job_id)

    async def create_from_analysis(
        self,
        raw_text: str,
        analysis: dict,
        url: str | None = None,
    ) -> Job:
        text_hash = self._compute_hash(raw_text)

        existing = await self.get_by_hash(text_hash)
        if existing:
            return existing

        job = Job(
            url=url,
            raw_text=raw_text,
            posting_text_hash=text_hash,
            title=analysis.get("title"),
            company=analysis.get("company"),
            experience=analysis.get("experience"),
            skills=analysis.get("skills") or None,
            technologies=analysis.get("technologies") or None,
            responsibilities=analysis.get("responsibilities") or None,
            qualifications=analysis.get("qualifications") or None,
            keywords=analysis.get("keywords") or None,
        )
        self._session.add(job)
        await self._session.commit()
        await self._session.refresh(job)
        return job
