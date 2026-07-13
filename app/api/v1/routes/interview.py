import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.schemas.interview import (
    DialogActionRequest,
    DialogStartRequest,
    DialogTextRequest,
    DialogTurnResponse,
    InterviewStateResponse,
    UserInfoRequest,
    UserInfoResponse,
)
from app.services.interview_state_machine import InterviewStateMachine

router = APIRouter()




def get_interview_machine(request: Request) -> InterviewStateMachine:
    """从 Request 中获取 Redis，构造访谈状态机实例。"""
    return InterviewStateMachine(request.app.state.redis)


# ---------- 会话状态 & 用户信息 ----------

@router.get("/interview/state/{session_id}", response_model=InterviewStateResponse)
async def get_interview_state(
    session_id: str,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> InterviewStateResponse:
    """根据 session_id 查询访谈会话的当前状态及扩展状态数据。"""
    return await machine.get_state(session_id)


@router.get("/interview/users/{user_id}/userinfo", response_model=UserInfoResponse)
async def get_interview_userinfo(
    user_id: str,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> UserInfoResponse:
    """获取指定用户的个人信息（姓名、性别、年龄等）。"""
    return await machine.get_userinfo(user_id)


@router.put("/interview/users/{user_id}/userinfo", response_model=UserInfoResponse)
async def save_interview_userinfo(
    user_id: str,
    payload: UserInfoRequest,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> UserInfoResponse:
    """保存或更新指定用户的个人信息。"""
    return await machine.save_userinfo(user_id, payload)


# ---------- 对话流程 ----------

@router.post("/interview/dialog/start", response_model=DialogTurnResponse)
async def start_dialog_flow(
    payload: DialogStartRequest,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> DialogTurnResponse:
    """创建对话会话，返回 session_id 等元数据（不含开场白，开场白由 /opening 接口流式输出）。"""
    return await machine.start_dialog(payload.session_id, payload.user_id)


@router.get("/interview/dialog/opening/{session_id}")
async def stream_opening(
    session_id: str,
    user_id: str | None = None,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> StreamingResponse:
    """SSE 流式输出开场白，逐 token 推送给前端。"""
    userinfo = await machine.get_userinfo(user_id) if user_id else None
    # 根据是否有用户的信息来判断当前的开场白是如何进行
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
    """处理用户在对话中的卡片选择等动作，推进对话状态并返回回复。"""
    return await machine.handle_dialog_action(payload)


@router.post("/interview/dialog/text", response_model=DialogTurnResponse)
async def handle_dialog_text(
    payload: DialogTextRequest,
    machine: InterviewStateMachine = Depends(get_interview_machine),
) -> DialogTurnResponse:
    """处理用户在对话中输入的文本消息，调用 LLM 生成访谈回复。"""
    return await machine.handle_dialog_text(payload)
