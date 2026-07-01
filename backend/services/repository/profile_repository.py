import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models.profile import UserProfile


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, profile_id: uuid.UUID) -> UserProfile | None:
        return await self._session.get(UserProfile, profile_id)

    async def create_from_analysis(
        self,
        analysis: dict,
        linkedin_url: str | None = None,
        github_url: str | None = None,
        portfolio_url: str | None = None,
    ) -> UserProfile:
        profile = UserProfile(
            name=analysis.get("name"),
            linkedin_url=linkedin_url,
            github_url=github_url,
            portfolio_url=portfolio_url,
            headline=analysis.get("headline"),
            summary=analysis.get("summary"),
            technical_skills=analysis.get("technical_skills") or None,
            soft_skills=analysis.get("soft_skills") or None,
            programming_languages=analysis.get("programming_languages") or None,
            frameworks=analysis.get("frameworks") or None,
            libraries=analysis.get("libraries") or None,
            databases=analysis.get("databases") or None,
            cloud_platforms=analysis.get("cloud_platforms") or None,
            devops_tools=analysis.get("devops_tools") or None,
            ai_ml_tools=analysis.get("ai_ml_tools") or None,
            development_tools=analysis.get("development_tools") or None,
            work_experience=analysis.get("work_experience") or None,
            education=analysis.get("education") or None,
            projects=analysis.get("projects") or None,
            github_repositories=analysis.get("github_repositories") or None,
            open_source_contributions=analysis.get("open_source_contributions") or None,
            certifications=analysis.get("certifications") or None,
            awards=analysis.get("awards") or None,
            achievements=analysis.get("achievements") or None,
            leadership_experience=analysis.get("leadership_experience") or None,
            volunteer_work=analysis.get("volunteer_work") or None,
            publications=analysis.get("publications") or None,
            links=analysis.get("links") or None,
        )
        self._session.add(profile)
        await self._session.commit()
        await self._session.refresh(profile)
        return profile
