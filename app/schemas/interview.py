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
DialogCardId = Literal[
    "start_interview",
    "need_guidance",
    "need_more_guidance",
    "relaxed_slow",
    "emotional_memory",
    "unknown_process",
    "restrained",
    "enthusiastic",
    "scattered",
    "worry_privacy",
    "dont_know_process",
    "dont_know_start_point",
    "worry_not_good_at_talking",
    "want_example_first",
    "custom_question",
]
DialogAction = Literal[
    "append_message",
    "show_entry_cards",
    "show_guidance_cards",
    "ready_to_interview",
    "enter_interview",
    "resume_interview",
]
CardGroup = Literal["entry", "guidance", "none"]
ResponseSource = Literal["llm", "fallback", "none"]


class InterviewCard(BaseModel):
    card_id: str
    label: str


class DialogMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class InterviewContext(BaseModel):
    session_id: str
    state: str = "INIT"
    previous_state: InterviewState | None = None
    guidance_round: int = 0
    max_guidance_rounds: int = 3
    created_at: datetime
    updated_at: datetime


class DialogStartRequest(BaseModel):
    session_id: str | None = None
    user_id: str | None = None


class DialogActionRequest(BaseModel):
    session_id: str | None = None
    card_id: DialogCardId
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
    cards: list[InterviewCard] = Field(default_factory=list)
    card_group: CardGroup = "none"
    guidance_round: int
    max_guidance_rounds: int
    can_continue_guidance: bool
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
