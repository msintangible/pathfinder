"""
Ownership coverage for /v1/resumes/generate and /v1/resumes/{id}/download.

ResumeVersion has no user_id of its own — ownership is derived through the
linked UserProfile.user_id, so both endpoints must 404 (not just reject)
when the caller isn't the owner, to avoid confirming another user's UUID exists.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.resume import router
from core.security import get_current_user, get_current_user_allow_query_token
from database.session import get_db
from models.job import Job
from models.profile import UserProfile
from models.user import User

_OWNER_ID = uuid.uuid4()
_OTHER_USER_ID = uuid.uuid4()


def _job(job_id: uuid.UUID) -> Job:
    return Job(id=job_id, raw_text="x", analyzed_at=datetime.now(timezone.utc))


_REPORT = {
    "ats_score_before": 87.5,
    "ats_score_after": 87.5,
    "matched_keywords_before": 1,
    "matched_keywords_after": 1,
    "keywords_added": [],
    "keywords_skipped": [],
    "unused_candidate_skills": [],
    "skills_reordered": False,
    "summary_rewritten": False,
    "experience_bullets_modified": 0,
    "projects_modified": 0,
    "highlights": [],
}

_GENERATION_RESULT = {
    "optimized_resume": {
        "headline": "Engineer",
        "summary": "Tailored summary",
        "skills": [],
        "experience": [],
        "projects": [],
        "changes_summary": [],
    },
    "matched_keywords": ["python"],
    "missing_keywords": [],
    "added_keywords": [],
    "ats_score": 87.5,
    "patches": [],
    "render_layout": None,
    "layout_preserved": False,
    "report": _REPORT,
}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: User(id=_OWNER_ID)
    app.dependency_overrides[get_current_user_allow_query_token] = lambda: User(id=_OWNER_ID)
    return TestClient(app)


def test_generate_requires_authentication():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    unauthenticated_client = TestClient(app)

    resp = unauthenticated_client.post(
        "/v1/resumes/generate",
        json={"user_profile_id": str(uuid.uuid4()), "job_id": str(uuid.uuid4())},
    )

    assert resp.status_code == 401


def test_generate_rejects_other_users_profile(client):
    job_id, profile_id = uuid.uuid4(), uuid.uuid4()
    with patch("api.v1.resume.JobRepository") as mock_job_repo_cls, \
         patch("api.v1.resume.ProfileRepository") as mock_profile_repo_cls:
        mock_job_repo_cls.return_value.get_by_id = AsyncMock(return_value=_job(job_id))
        mock_profile_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=UserProfile(id=profile_id, user_id=_OTHER_USER_ID)
        )

        resp = client.post(
            "/v1/resumes/generate",
            json={"user_profile_id": str(profile_id), "job_id": str(job_id)},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Profile not found"


def test_generate_succeeds_for_own_profile(client, tmp_path):
    """No source document at all — must fall back to the generic template renderer."""
    job_id, profile_id = uuid.uuid4(), uuid.uuid4()
    with patch("api.v1.resume.JobRepository") as mock_job_repo_cls, \
         patch("api.v1.resume.ProfileRepository") as mock_profile_repo_cls, \
         patch("api.v1.resume.ResumeGenerationAgent") as mock_agent_cls, \
         patch(
             "api.v1.resume.render_within_page_limit",
             return_value=(b"%PDF-1.4 fake", _GENERATION_RESULT["optimized_resume"]),
         ) as mock_render_within_page_limit, \
         patch("api.v1.resume.LocalResumeStorage") as mock_storage_cls, \
         patch("api.v1.resume.ResumeRepository") as mock_resume_repo_cls:
        mock_job_repo_cls.return_value.get_by_id = AsyncMock(return_value=_job(job_id))
        mock_profile_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=UserProfile(id=profile_id, user_id=_OWNER_ID)
        )
        mock_agent_cls.return_value.generate = AsyncMock(return_value=_GENERATION_RESULT)
        mock_storage_cls.return_value.save.return_value = str(tmp_path / "resume.pdf")

        resume_id = uuid.uuid4()
        from models.application import ResumeVersion
        mock_resume_repo_cls.return_value.create_from_generation = AsyncMock(
            return_value=ResumeVersion(
                id=resume_id,
                user_profile_id=profile_id,
                job_id=job_id,
                content=_GENERATION_RESULT["optimized_resume"],
                matched_keywords=["python"],
                missing_keywords=[],
                ats_score=87.5,
                report=_REPORT,
                layout_preserved=False,
            )
        )

        resp = client.post(
            "/v1/resumes/generate",
            json={"user_profile_id": str(profile_id), "job_id": str(job_id)},
        )

        assert resp.status_code == 200
        assert resp.json()["download_url"] == f"/v1/resumes/{resume_id}/download"
        assert resp.json()["layout_preserved"] is False
        assert resp.json()["report"] == _REPORT
        mock_render_within_page_limit.assert_called_once()
        assert mock_resume_repo_cls.return_value.create_from_generation.call_args.kwargs["layout_preserved"] is False
        assert mock_resume_repo_cls.return_value.create_from_generation.call_args.kwargs["report"] == _REPORT


def test_generate_always_uses_template_renderer_regardless_of_source_document(client, tmp_path):
    """The HTML/Jinja2 template (resume_renderer.render_pdf) is now the sole
    renderer — a profile with a real .docx/.pdf source document must still
    render via the generic template, never the in-place docx/pdf renderers."""
    job_id, profile_id = uuid.uuid4(), uuid.uuid4()
    source_path = tmp_path / "source.docx"
    source_path.write_bytes(b"fake docx bytes")

    with patch("api.v1.resume.JobRepository") as mock_job_repo_cls, \
         patch("api.v1.resume.ProfileRepository") as mock_profile_repo_cls, \
         patch("api.v1.resume.ResumeGenerationAgent") as mock_agent_cls, \
         patch(
             "api.v1.resume.render_within_page_limit",
             return_value=(b"%PDF-1.4 fake", _GENERATION_RESULT["optimized_resume"]),
         ) as mock_render_within_page_limit, \
         patch("api.v1.resume.LocalResumeStorage") as mock_storage_cls, \
         patch("api.v1.resume.ResumeRepository") as mock_resume_repo_cls:
        mock_job_repo_cls.return_value.get_by_id = AsyncMock(return_value=_job(job_id))
        mock_profile_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=UserProfile(
                id=profile_id, user_id=_OWNER_ID,
                source_document_path=str(source_path), source_document_format="docx",
            )
        )
        mock_agent_cls.return_value.generate = AsyncMock(return_value=_GENERATION_RESULT)
        mock_storage_cls.return_value.save.return_value = str(tmp_path / "rendered.pdf")

        resume_id = uuid.uuid4()
        from models.application import ResumeVersion
        mock_resume_repo_cls.return_value.create_from_generation = AsyncMock(
            return_value=ResumeVersion(
                id=resume_id, user_profile_id=profile_id, job_id=job_id,
                content=_GENERATION_RESULT["optimized_resume"],
                matched_keywords=["python"], missing_keywords=[], ats_score=87.5,
                report=_REPORT,
                rendered_file_url=str(tmp_path / "rendered.pdf"), rendered_file_format="pdf",
                layout_preserved=False,
            )
        )

        resp = client.post(
            "/v1/resumes/generate",
            json={"user_profile_id": str(profile_id), "job_id": str(job_id)},
        )

        assert resp.status_code == 200
        assert resp.json()["layout_preserved"] is False
        mock_render_within_page_limit.assert_called_once()
        call_kwargs = mock_resume_repo_cls.return_value.create_from_generation.call_args.kwargs
        assert call_kwargs["rendered_file_format"] == "pdf"
        assert call_kwargs["layout_preserved"] is False


def test_download_requires_authentication():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    unauthenticated_client = TestClient(app)

    resp = unauthenticated_client.get(f"/v1/resumes/{uuid.uuid4()}/download")

    assert resp.status_code == 401


def test_download_rejects_other_users_resume(client, tmp_path):
    from models.application import ResumeVersion

    resume_id, profile_id = uuid.uuid4(), uuid.uuid4()
    pdf_path = tmp_path / "resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    with patch("api.v1.resume.ResumeRepository") as mock_resume_repo_cls, \
         patch("api.v1.resume.ProfileRepository") as mock_profile_repo_cls:
        mock_resume_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=ResumeVersion(
                id=resume_id, user_profile_id=profile_id, job_id=uuid.uuid4(),
                content={}, rendered_file_url=str(pdf_path), rendered_file_format="pdf",
            )
        )
        mock_profile_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=UserProfile(id=profile_id, user_id=_OTHER_USER_ID)
        )

        resp = client.get(f"/v1/resumes/{resume_id}/download")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Resume not found"


def test_download_succeeds_for_owned_resume(client, tmp_path):
    from models.application import ResumeVersion

    resume_id, profile_id = uuid.uuid4(), uuid.uuid4()
    pdf_path = tmp_path / "resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    with patch("api.v1.resume.ResumeRepository") as mock_resume_repo_cls, \
         patch("api.v1.resume.ProfileRepository") as mock_profile_repo_cls:
        mock_resume_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=ResumeVersion(
                id=resume_id, user_profile_id=profile_id, job_id=uuid.uuid4(),
                content={}, rendered_file_url=str(pdf_path), rendered_file_format="pdf",
            )
        )
        mock_profile_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=UserProfile(id=profile_id, user_id=_OWNER_ID)
        )

        resp = client.get(f"/v1/resumes/{resume_id}/download")

        assert resp.status_code == 200
        assert resp.content == b"%PDF-1.4 fake"


def test_download_accepts_token_via_query_param_when_no_header_present(tmp_path):
    """A plain browser-tab navigation can't attach an Authorization header, so
    the download route must also accept ?token=... — see
    get_current_user_allow_query_token."""
    from core.security import create_anonymous_token
    from models.application import ResumeVersion

    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    no_header_client = TestClient(app)

    resume_id, profile_id = uuid.uuid4(), uuid.uuid4()
    pdf_path = tmp_path / "resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    token = create_anonymous_token(_OWNER_ID)

    with patch("api.v1.resume.ResumeRepository") as mock_resume_repo_cls, \
         patch("api.v1.resume.ProfileRepository") as mock_profile_repo_cls, \
         patch("core.security.UserRepository") as mock_user_repo_cls:
        mock_resume_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=ResumeVersion(
                id=resume_id, user_profile_id=profile_id, job_id=uuid.uuid4(),
                content={}, rendered_file_url=str(pdf_path), rendered_file_format="pdf",
            )
        )
        mock_profile_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=UserProfile(id=profile_id, user_id=_OWNER_ID)
        )
        mock_user_repo_cls.return_value.get_by_id = AsyncMock(return_value=User(id=_OWNER_ID))

        resp = no_header_client.get(f"/v1/resumes/{resume_id}/download", params={"token": token})

        assert resp.status_code == 200
        assert resp.content == b"%PDF-1.4 fake"


def test_download_serves_docx_with_the_right_media_type(client, tmp_path):
    from models.application import ResumeVersion

    resume_id, profile_id = uuid.uuid4(), uuid.uuid4()
    docx_path = tmp_path / "resume.docx"
    docx_path.write_bytes(b"fake docx bytes")

    with patch("api.v1.resume.ResumeRepository") as mock_resume_repo_cls, \
         patch("api.v1.resume.ProfileRepository") as mock_profile_repo_cls:
        mock_resume_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=ResumeVersion(
                id=resume_id, user_profile_id=profile_id, job_id=uuid.uuid4(),
                content={}, rendered_file_url=str(docx_path), rendered_file_format="docx",
            )
        )
        mock_profile_repo_cls.return_value.get_by_id = AsyncMock(
            return_value=UserProfile(id=profile_id, user_id=_OWNER_ID)
        )

        resp = client.get(f"/v1/resumes/{resume_id}/download")

        assert resp.status_code == 200
        assert resp.content == b"fake docx bytes"
        assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert resp.headers["content-disposition"].endswith(f'resume-{resume_id}.docx"')
