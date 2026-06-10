"""
单条情绪分析处理器。

对齐落地方案 §5.1.2 / §5.2.2：每轮用户输入后做低字段结构化判断，
供采访策略和 demo 展示使用。
"""

import json
import logging
from uuid import uuid4

from core.llm_client import llm_client
from core.models import EmotionAnalysisOutput, SessionState
from core.session_manager import session_manager
from config.prompts_config import (
    EMOTION_SINGLE_SYSTEM_PROMPT,
    EMOTION_SINGLE_USER_PROMPT_TEMPLATE,
)

logger = logging.getLogger(__name__)


def analyze_single_message_emotion(session: SessionState, user_message: str) -> EmotionAnalysisOutput:
    """分析最新一条用户输入的情绪和对话信号。"""
    message_id = f"msg_{uuid4().hex[:8]}"
    last_assistant_message = _get_last_assistant_message(session)
    user_profile_preferences = json.dumps(
        {
            "communication_preference": session.user_profile.communication_preference,
            "avoid_topics": session.user_profile.avoid_topics,
        },
        ensure_ascii=False,
    )

    user_prompt = EMOTION_SINGLE_USER_PROMPT_TEMPLATE.format(
        message_id=message_id,
        session_id=session.session_id,
        user_message=user_message,
        last_assistant_message=last_assistant_message,
        input_latency_seconds=0,
        input_length=len(user_message),
        recent_emotion_summary=session.session_context.last_emotion,
        user_profile_preferences=user_profile_preferences,
    )

    try:
        result = llm_client.chat_json(EMOTION_SINGLE_SYSTEM_PROMPT, user_prompt)
        emotion = EmotionAnalysisOutput(**result)
    except Exception as e:
        logger.warning("情绪分析失败，使用默认情绪结果: %s", e)
        emotion = _default_emotion_analysis(message_id, session, user_message)

    session.session_context.last_emotion = emotion.primary_emotion
    session.chat_history.append(
        {
            "role": "emotion",
            "content": emotion.model_dump(),
        }
    )
    session_manager.update_session(session)
    return emotion


def _get_last_assistant_message(session: SessionState) -> str:
    for msg in reversed(session.chat_history):
        if msg.get("role") == "assistant":
            return str(msg.get("content", ""))
    return ""


def _default_emotion_analysis(
    message_id: str,
    session: SessionState,
    user_message: str,
) -> EmotionAnalysisOutput:
    text = user_message.strip()
    if any(word in text for word in ["不想说", "别问", "不方便", "隐私"]):
        return EmotionAnalysisOutput(
            message_id=message_id,
            session_id=session.session_id,
            primary_emotion="defensive",
            valence=-0.4,
            arousal=0.5,
            confidence=0.45,
            risk_level="medium",
            engagement_level="low",
            boundary_signal={"has_refusal": True, "has_privacy_concern": True},
            conversation_signal={"input_intent": "refuse", "answer_quality": "short_answer", "should_slow_down": True, "should_ask_follow_up": False},
            recommended_action={"action_type": "explain_boundary", "reason": "用户出现拒绝或隐私边界信号"},
        )
    if len(text) <= 8:
        return EmotionAnalysisOutput(
            message_id=message_id,
            session_id=session.session_id,
            primary_emotion="apathy",
            confidence=0.35,
            risk_level="low",
            engagement_level="low",
            conversation_signal={"input_intent": "unclear", "answer_quality": "short_answer", "should_slow_down": True, "should_ask_follow_up": True},
            recommended_action={"action_type": "soft_follow_up", "reason": "用户回复较短，建议降低问题压力"},
        )
    return EmotionAnalysisOutput(
        message_id=message_id,
        session_id=session.session_id,
        primary_emotion="engagement",
        confidence=0.4,
        risk_level="low",
        engagement_level="medium",
        conversation_signal={"input_intent": "continue_story", "answer_quality": "has_fact", "should_slow_down": False, "should_ask_follow_up": True},
        recommended_action={"action_type": "normal_follow_up", "reason": "用户仍在继续讲述"},
    )
