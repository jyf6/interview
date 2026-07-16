from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.schemas.biography import (
    BiographyCreateRequest,
    BiographyResponse,
    HighlightMessageRequest,
    HighlightSessionRequest,
    HighlightTurnResponse,
    OutlineEditRequest,
    OutlineResponse,
)
from app.services.biography_store import BiographyStore
from app.services.highlight_interview import HighlightInterviewService
from app.services.outline_service import OutlineService

router = APIRouter()


def get_service(request: Request) -> OutlineService:
    return OutlineService(request.app.state.biography_store)


def get_highlight_service(request: Request) -> HighlightInterviewService:
    return HighlightInterviewService(request.app.state.redis, get_service(request), settings.session_ttl_seconds)


@router.post("/biographies", response_model=BiographyResponse)
def create_biography(payload: BiographyCreateRequest, request: Request) -> BiographyResponse:
    return get_service(request).store.create_biography(payload.interviewee_id)


@router.post("/biographies/{biography_id}/highlight-sessions", response_model=HighlightTurnResponse)
async def start_highlight_session(
    biography_id: str,
    payload: HighlightSessionRequest,
    request: Request,
) -> HighlightTurnResponse:
    try:
        return await get_highlight_service(request).start(biography_id, payload.session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/biographies/{biography_id}/highlight-sessions/{session_id}/messages",
    response_model=HighlightTurnResponse,
)
async def send_highlight_message(
    biography_id: str,
    session_id: str,
    payload: HighlightMessageRequest,
    request: Request,
) -> HighlightTurnResponse:
    if payload.session_id != session_id:
        raise HTTPException(status_code=400, detail="session_id_mismatch")
    try:
        service = get_highlight_service(request)
        if not await service.belongs_to(session_id, biography_id):
            raise HTTPException(status_code=403, detail="biography_id_mismatch")
        result = await service.handle(session_id, payload.content)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/outlines/{outline_id}", response_model=OutlineResponse)
def get_outline(outline_id: str, request: Request) -> OutlineResponse:
    try:
        return get_service(request).store.get_outline(outline_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/outlines/{outline_id}", response_model=OutlineResponse)
def update_outline(outline_id: str, payload: OutlineEditRequest, request: Request) -> OutlineResponse:
    try:
        return get_service(request).store.replace_draft(outline_id, payload.chapters)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/outlines/{outline_id}/publish", response_model=OutlineResponse)
def publish_outline(outline_id: str, request: Request) -> OutlineResponse:
    try:
        return get_service(request).store.publish_outline(outline_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
