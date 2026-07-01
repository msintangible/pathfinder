from fastapi import APIRouter

from api.v1 import jobs, resume

router = APIRouter()
router.include_router(jobs.router)
router.include_router(resume.router)
