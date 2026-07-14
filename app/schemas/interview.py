from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


InterviewState = Literal[
    "INIT",
    "OPENING_GENERATING",
    "OPENING_DELIVERED",
    "GUIDANCE_CARD",
    "READY_TO_INTERVIEW",
    "INTERVIEWING",
    "end",
]
DialogAction = Literal[
    "append_message",
    "ready_to_interview",
    "resume_interview",
]
ResponseSource = Literal["llm", "fallback", "none"]


class DialogMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class InterviewContext(BaseModel):
    session_id: str
    state: str = "INIT"
    previous_state: InterviewState | None = None
    created_at: datetime
    updated_at: datetime


class DialogStartRequest(BaseModel):
    session_id: str | None = None
    user_id: str | None = None


class DialogActionRequest(BaseModel):
    session_id: str | None = None
    card_id: str
    selected_text: str | None = None
    question: str | None = None


class DialogTextRequest(BaseModel):
    session_id: str | None = None
    content: str = Field(min_length=1)


class DialogTurnResponse(BaseModel):
    session_id: str
    current_state: InterviewState
    previous_state: InterviewState | None = None
    action: DialogAction
    message: DialogMessage | None = None
    response_source: ResponseSource = "none"
    state_interview: dict[str, object] = Field(default_factory=dict)


class InterviewStateResponse(BaseModel):
    session_id: str
    state: InterviewState
    state_interview: dict[str, object] = Field(default_factory=dict)


class UserInfoRequest(BaseModel):
    name: str = ""
    gender: str = ""
    age: str = ""
    last_used_at: str = ""


class UserInfoResponse(BaseModel):
    user_id: str
    userinfo: dict[str, str] = Field(default_factory=dict)
