from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentMessageCreate,
    AgentMessageRead,
    AgentSessionCreate,
    AgentSessionRead,
)
from app.core.config import settings
from app.services.llm_service import DashScopeChatService, LLMServiceError
from app.services.session_store import SessionStore

router = APIRouter()


def get_session_store(request: Request) -> SessionStore:
    return SessionStore(request.app.state.redis)


def get_chat_service() -> DashScopeChatService:
    return DashScopeChatService()


@router.post("", response_model=AgentSessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: AgentSessionCreate,
    store: SessionStore = Depends(get_session_store),
) -> AgentSessionRead:
    return await store.create_session(payload)


@router.get("/{session_id}", response_model=AgentSessionRead)
async def get_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> AgentSessionRead:
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


@router.post("/{session_id}/messages", response_model=AgentMessageRead, status_code=status.HTTP_201_CREATED)
async def append_message(
    session_id: str,
    payload: AgentMessageCreate,
    store: SessionStore = Depends(get_session_store),
) -> AgentMessageRead:
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return await store.append_message(session_id, payload)


@router.post("/{session_id}/chat", response_model=AgentChatResponse, status_code=status.HTTP_201_CREATED)
async def chat_with_session(
    session_id: str,
    payload: AgentChatRequest,
    store: SessionStore = Depends(get_session_store),
    chat_service: DashScopeChatService = Depends(get_chat_service),
) -> AgentChatResponse:
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    user_message = await store.append_message(
        session_id,
        AgentMessageCreate(role="user", content=payload.content),
    )
    history = await store.list_messages(session_id)

    try:
        assistant_content = await chat_service.generate_reply(history, goal=session.goal)
    except LLMServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    assistant_message = await store.append_message(
        session_id,
        AgentMessageCreate(role="assistant", content=assistant_content),
    )
    return AgentChatResponse(
        session_id=session_id,
        model=settings.dashscope_model,
        user_message=user_message,
        assistant_message=assistant_message,
    )


@router.get("/{session_id}/messages", response_model=list[AgentMessageRead])
async def list_messages(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> list[AgentMessageRead]:
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return await store.list_messages(session_id)
