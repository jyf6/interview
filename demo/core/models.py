"""
数据模型定义
所有 API 请求/响应和内部状态的 Pydantic 模型
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ===== 状态机 =====

class SystemState(str, Enum):
    INIT = "INIT"
    OPENING_GENERATING = "OPENING_GENERATING"
    OPENING_DELIVERED = "OPENING_DELIVERED"
    GUIDANCE_CARD = "GUIDANCE_CARD"
    READY_TO_INTERVIEW = "READY_TO_INTERVIEW"
    INTERVIEWING = "INTERVIEWING"
    PAUSED = "PAUSED"
    RECONNECTING = "RECONNECTING"
    COMPLETED = "COMPLETED"


# ===== 用户画像 =====

class UserProfile(BaseModel):
    nickname: str = "阿姨/叔叔"
    age_range: str = "60-75"
    known_life_stage: list[str] = Field(default_factory=list)
    communication_preference: str = "温和、慢节奏"
    avoid_topics: list[str] = Field(default_factory=list)
    is_new_user: bool = True


# ===== 会话上下文 =====

class SessionContext(BaseModel):
    is_first_visit: bool = True
    last_state: Optional[SystemState] = None
    last_story_summary: Optional[str] = None
    unfinished_slots: list[str] = Field(default_factory=list)
    days_since_last_visit: int = 0


# ===== 开场白 =====

class SuggestedCard(BaseModel):
    card_id: str
    label: str
    next_action: str


class RiskNotes(BaseModel):
    avoid_topics: list[str] = Field(default_factory=list)
    do_not_ask: list[str] = Field(default_factory=list)


class OpeningOutput(BaseModel):
    opening_type: str = "first_user"
    main_message: str = ""
    trust_sentence: str = ""
    micro_question: str = ""
    suggested_cards: list[SuggestedCard] = Field(default_factory=list)
    risk_notes: RiskNotes = Field(default_factory=RiskNotes())


# ===== 卡片引导 =====

class GuidanceCard(BaseModel):
    card_id: str
    label: str
    next_action: str


class GuidanceOutput(BaseModel):
    selected_card_id: str = ""
    response_strategy: str = ""
    assistant_message: str = ""
    next_question: str = ""
    next_cards: list[GuidanceCard] = Field(default_factory=list)
    can_enter_interview: bool = True
    recommended_next_state: str = "GUIDANCE_CARD"


# ===== 产品入场引导 =====

class OnboardingStep(BaseModel):
    step_id: str
    sequence: int
    title: str
    body: str
    target_key: str
    placement: str = "bottom"
    primary_action_label: str = "下一步"


class OnboardingGuideResponse(BaseModel):
    guide_id: str
    version: str
    title: str
    description: str = ""
    steps: list[OnboardingStep] = Field(default_factory=list)
    target_contract: dict[str, str] = Field(default_factory=dict)


# ===== API 请求/响应 =====

class StartSessionRequest(BaseModel):
    user_id: str
    entry_source: str = "app_home"


class CardSelectRequest(BaseModel):
    card_id: str


class ChatRequest(BaseModel):
    message: str


class SessionResponse(BaseModel):
    session_id: str
    state: str
    message: Optional[OpeningOutput] = None
    guidance: Optional[GuidanceOutput] = None
    cards: list[SuggestedCard] = Field(default_factory=list)
    assistant_text: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    state: str
    assistant_text: str
    can_continue: bool = True


# ===== 会话存储 =====

class SessionState(BaseModel):
    session_id: str
    user_id: str
    current_state: SystemState = SystemState.INIT
    previous_state: Optional[SystemState] = None
    user_profile: UserProfile = Field(default_factory=UserProfile)
    session_context: SessionContext = Field(default_factory=SessionContext)
    chat_history: list[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
