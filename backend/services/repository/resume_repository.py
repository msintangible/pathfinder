import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models.application import ResumeVersion


class ResumeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, resume_id: uuid.UUID) -> ResumeVersion | None:
        return await self._session.get(ResumeVersion, resume_id)

    async def create_from_generation(
        self,
        user_profile_id: uuid.UUID,
        job_id: uuid.UUID,
        optimized_resume: dict,
        matched_keywords: list[str],
        missing_keywords: list[str],
        ats_score: float,
        added_keywords: list[str] | None = None,
        rendered_file_url: str | None = None,
        rendered_file_format: str | None = None,
        layout_preserved: bool = False,
    ) -> ResumeVersion:
        resume = ResumeVersion(
            user_profile_id=user_profile_id,
            job_id=job_id,
            content=optimized_resume,
            matched_keywords=matched_keywords or None,
            missing_keywords=missing_keywords or None,
            added_keywords=added_keywords or None,
            ats_score=ats_score,
            rendered_file_url=rendered_file_url,
            rendered_file_format=rendered_file_format,
            layout_preserved=layout_preserved,
        )
        self._session.add(resume)
        await self._session.commit()
        await self._session.refresh(resume)
        return resume
