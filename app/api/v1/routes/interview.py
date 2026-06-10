from fastapi import APIRouter, Depends, Request

from app.schemas.interview import (
    DialogActionRequest,
    DialogStartRequest,
    DialogTurnResponse,
    EntryCardSelection,
    GuidanceCardResponse,
    GuidanceCardSelection,
    OnboardingGuideResponse,
    StartInterviewResponse,
)
from app.services.interview_state_machine import InterviewStateMachine
from app.services.onboarding_service import OnboardingService

router = APIRouter()


def get_interview_machine(request: Request) -> InterviewStateMachine:
    return InterviewStateMachine(request.app.state.redis)


def get_onboarding_service() -> OnboardingService:
    return OnboardingService()


@router.get("/interview/onboarding/guide", response_model=OnboardingGuideResponse)
async def get_onboarding_guide(
    service: OnboardingService = Depends(get_onboarding_service),
) -> OnboardingGuideResponse:
    return service.build_guide()


@router.get("/strat-interview", response_model=StartInterviewResponse)
async def start_interview_flow(
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> StartInterviewResponse:
    return await machine.start()


@router.post("/strat-interview", response_model=StartInterviewResponse)
async def select_entry_card(
    payload: EntryCardSelection,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> StartInterviewResponse:
    return await machine.select_entry_card(payload)


@router.post("/interview/guidance-card", response_model=GuidanceCardResponse)
async def select_guidance_card(
    payload: GuidanceCardSelection,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> GuidanceCardResponse:
    return await machine.select_guidance_card(payload)


@router.post("/interview/dialog/start", response_model=DialogTurnResponse)
async def start_dialog_flow(
    payload: DialogStartRequest,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> DialogTurnResponse:
    return await machine.start_dialog(payload.session_id)


@router.post("/interview/dialog/actions", response_model=DialogTurnResponse)
async def handle_dialog_action(
    payload: DialogActionRequest,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> DialogTurnResponse:
    return await machine.handle_dialog_action(payload)
