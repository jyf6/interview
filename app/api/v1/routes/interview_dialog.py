import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.v1.routes.interview_dependencies import get_interview_machine
from app.schemas.interview import (
    DialogActionRequest,
    DialogStartRequest,
    DialogTextRequest,
    DialogTurnResponse,
)
from app.services.interview_state_machine import InterviewStateMachine

router = APIRouter()


@router.post("/interview/dialog/start", response_model=DialogTurnResponse)
async def start_dialog_flow(
    payload: DialogStartRequest,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> DialogTurnResponse:
    return await machine.start_dialog(payload.session_id, payload.user_id)


@router.get("/interview/dialog/opening/{session_id}")
async def stream_opening(
    session_id: str,
    user_id: str | None = None,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> StreamingResponse:
    userinfo = await machine.get_userinfo(user_id) if user_id else None
    token_gen = await machine.opening.build_opening_stream(
        userinfo=userinfo.userinfo if userinfo else None
    )

    async def event_stream():
        full_text = ""
        async for token in token_gen:
            full_text += token
            yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        await machine.save_opening_message(session_id, full_text)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/interview/dialog/actions", response_model=DialogTurnResponse)
async def handle_dialog_action(
    payload: DialogActionRequest,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> DialogTurnResponse:
    return await machine.handle_dialog_action(payload)


@router.post("/interview/dialog/text", response_model=DialogTurnResponse)
async def handle_dialog_text(
    payload: DialogTextRequest,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> DialogTurnResponse:
    return await machine.handle_dialog_text(payload)
