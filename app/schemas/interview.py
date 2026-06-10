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
]
EntryCardId = Literal["start_interview", "need_guidance", "need_more_guidance"]
GuidanceCardId = Literal[
    "dont_know_process",
    "dont_know_start_point",
    "worry_not_good_at_talking",
    "worry_privacy",
    "want_example_first",
    "need_guidance",
    "need_more_guidance",
]
DialogCardId = Literal[
    "start_interview",
    "need_guidance",
    "need_more_guidance",
    "dont_know_process",
    "dont_know_start_point",
    "worry_not_good_at_talking",
    "worry_privacy",
    "want_example_first",
]
DialogAction = Literal[
    "append_message",
    "show_entry_cards",
    "show_guidance_cards",
    "ready_to_interview",
    "enter_interview",
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
    current_state: InterviewState = "INIT"
    previous_state: InterviewState | None = None
    guidance_round: int = 0
    max_guidance_rounds: int = 3
    created_at: datetime
    updated_at: datetime


class StartInterviewResponse(BaseModel):
    session_id: str
    current_state: InterviewState
    cards: list[InterviewCard]
    guidance_cards: list[InterviewCard] = Field(default_factory=list)
    assistant_message: str
    guidance_round: int
    max_guidance_rounds: int


class EntryCardSelection(BaseModel):
    session_id: str | None = None
    card_id: EntryCardId


class GuidanceCardSelection(BaseModel):
    session_id: str
    card_id: GuidanceCardId


class GuidanceCardResponse(BaseModel):
    session_id: str
    assistant_message: str
    next_cards: list[InterviewCard]
    recommended_next_state: InterviewState
    current_state: InterviewState
    guidance_round: int
    max_guidance_rounds: int
    can_continue_guidance: bool
    response_source: Literal["llm", "fallback"] = "fallback"


class DialogStartRequest(BaseModel):
    session_id: str | None = None


class DialogActionRequest(BaseModel):
    session_id: str | None = None
    card_id: DialogCardId


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


class OnboardingStep(BaseModel):
    step_id: str
    sequence: int
    title: str
    body: str
    target_key: str
    placement: Literal["top", "right", "bottom", "left", "center"] = "bottom"
    primary_action_label: str = "下一步"


class OnboardingGuideResponse(BaseModel):
    guide_id: str
    version: str
    title: str
    description: str
    steps: list[OnboardingStep]
    target_contract: dict[str, str]
