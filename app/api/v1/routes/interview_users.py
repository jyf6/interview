from fastapi import APIRouter, Depends

from app.api.v1.routes.interview_dependencies import get_interview_machine
from app.schemas.interview import UserInfoRequest, UserInfoResponse
from app.services.interview_state_machine import InterviewStateMachine

router = APIRouter()


@router.get("/interview/users/{user_id}/userinfo", response_model=UserInfoResponse)
async def get_interview_userinfo(
    user_id: str,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> UserInfoResponse:
    return await machine.get_userinfo(user_id)


@router.put("/interview/users/{user_id}/userinfo", response_model=UserInfoResponse)
async def save_interview_userinfo(
    user_id: str,
    payload: UserInfoRequest,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> UserInfoResponse:
    return await machine.save_userinfo(user_id, payload)
