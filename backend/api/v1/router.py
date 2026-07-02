from fastapi import APIRouter

from api.v1 import auth, jobs, profile, resume

router = APIRouter()
router.include_router(auth.router)
router.include_router(jobs.router)
router.include_router(profile.router)
router.include_router(resume.router)
