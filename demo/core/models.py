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
    EMOTION_REVIEW = "EMOTION_REVIEW"
    COMFORTING = "COMFORTING"
    RESUME_INTERVIEW_CHECK = "RESUME_INTERVIEW_CHECK"
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
    last_emotion: str = "neutral"
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


# ===== 情绪分析 =====

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
        """用于 demo 展示的极简情绪摘要。"""
        emotion_labels = {
            "joy": "愉悦",
            "engagement": "专注",
            "nostalgia": "怀念",
            "anxiety": "焦虑/警惕",
            "frustration": "烦躁/沮丧",
            "apathy": "敷衍/冷淡",
            "defensive": "防御/抵抗",
            "sadness": "悲伤",
        }
        risk_labels = {
            "low": "低",
            "medium": "中",
            "high": "高",
        }
        engagement_labels = {
            "low": "低",
            "medium": "中",
            "high": "高",
        }
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
        if self.recommended_action.action_type:
            action = action_labels.get(self.recommended_action.action_type, self.recommended_action.action_type)
            parts.append(f"动作={action}")
        return "；".join(parts)


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
