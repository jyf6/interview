from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BoundarySignal(BaseModel):
    has_privacy_concern: bool = False
    has_refusal: bool = False
    sensitive_topic: bool = False
    do_not_probe: list[str] = Field(default_factory=list)


class ConversationSignal(BaseModel):
    input_intent: str = "unclear"
    answer_quality: str = "short_answer"
    should_slow_down: bool = False
    should_ask_follow_up: bool = True


class RecommendedAction(BaseModel):
    action_type: str = "normal_follow_up"
    reason: str = ""
    allowed_question_type: list[str] = Field(default_factory=list)
    forbidden_question_type: list[str] = Field(default_factory=list)


class EmotionAnalysisOutput(BaseModel):
    message_id: str = ""
    session_id: str = ""
    primary_emotion: str = "engagement"
    secondary_emotions: list[str] = Field(default_factory=list)
    valence: float = 0.0
    arousal: float = 0.0
    confidence: float = 0.0
    risk_level: str = "low"
    engagement_level: str = "medium"
    boundary_signal: BoundarySignal = Field(default_factory=BoundarySignal)
    conversation_signal: ConversationSignal = Field(default_factory=ConversationSignal)
    recommended_action: RecommendedAction = Field(default_factory=RecommendedAction)
    storage_ttl_minutes: int = 180

    def to_display_text(self) -> str:
        emotion_labels = {
            "joy": "愉悦",
            "engagement": "投入",
            "nostalgia": "怀旧",
            "anxiety": "焦虑/担心",
            "frustration": "烦躁/沮丧",
            "apathy": "冷淡/低参与",
            "defensive": "防御/抗拒",
            "sadness": "悲伤",
        }
        risk_labels = {"low": "低", "medium": "中", "high": "高"}
        engagement_labels = {"low": "低", "medium": "中", "high": "高"}
        action_labels = {
            "normal_follow_up": "正常追问",
            "soft_follow_up": "柔和追问",
            "comfort": "先安抚",
            "explain_boundary": "解释边界",
            "change_topic": "换话题",
            "pause": "暂停",
        }
        parts = [
            f"情绪={emotion_labels.get(self.primary_emotion, self.primary_emotion)}",
            f"风险={risk_labels.get(self.risk_level, self.risk_level)}",
            f"参与度={engagement_labels.get(self.engagement_level, self.engagement_level)}",
        ]
        if self.conversation_signal.should_slow_down:
            parts.append("建议放慢")
        if self.boundary_signal.has_refusal or self.boundary_signal.has_privacy_concern:
            parts.append("注意边界")
        action = action_labels.get(self.recommended_action.action_type)
        if action:
            parts.append(f"动作={action}")
        return "；".join(parts)


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
    "need_guidance",
    "need_more_guidance",
    "custom_question",
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


class InterviewStateResponse(BaseModel):
    session_id: str
    state: InterviewState


class UserInfoRequest(BaseModel):
    name: str = ""
    gender: str = ""
    age: str = ""
    last_used_at: str = ""


class UserInfoResponse(BaseModel):
    user_id: str
    userinfo: dict[str, str] = Field(default_factory=dict)


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
