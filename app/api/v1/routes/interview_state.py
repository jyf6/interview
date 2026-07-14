from fastapi import APIRouter, Depends

from app.api.v1.routes.interview_dependencies import get_interview_machine
from app.schemas.interview import InterviewStateResponse
from app.services.interview_state_machine import InterviewStateMachine

router = APIRouter()


@router.get("/interview/state/{session_id}", response_model=InterviewStateResponse)
async def get_interview_state(
    session_id: str,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> InterviewStateResponse:
    return await machine.get_state(session_id)
