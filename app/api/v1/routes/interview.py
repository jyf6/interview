from fastapi import APIRouter

from app.api.v1.routes import interview_dialog, interview_state, interview_users

router = APIRouter()
router.include_router(interview_state.router)
router.include_router(interview_users.router)
router.include_router(interview_dialog.router)
