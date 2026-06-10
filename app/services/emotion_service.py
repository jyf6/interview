import asyncio
import json
import logging
import time
from uuid import uuid4

from app.core.config import settings
from app.core.llm_client import emotion_llm
from app.core.perf import perf_span
from app.schemas.interview import (
    BoundarySignal,
    ConversationSignal,
    EmotionAnalysisOutput,
    RecommendedAction,
)

logger = logging.getLogger(__name__)

EMOTION_SINGLE_SYSTEM_PROMPT = (
    "你只做采访情绪分类。输出严格 JSON，不要 Markdown。"
    "不要做医学诊断。字段只允许：emotion,risk,engagement,action,slow,boundary。"
)

EMOTION_SINGLE_USER_PROMPT_TEMPLATE = """用户输入：{user_message}
上一句助手：{last_assistant_message}

取值：
emotion=joy|engagement|nostalgia|anxiety|frustration|apathy|defensive|sadness
risk=low|medium|high
engagement=low|medium|high
action=normal_follow_up|soft_follow_up|comfort|explain_boundary|change_topic|pause
slow=true|false
boundary=true|false

只输出一行 JSON，例如：
{{"emotion":"engagement","risk":"low","engagement":"medium","action":"normal_follow_up","slow":false,"boundary":false}}"""

EMOTION_CACHE_TTL_SECONDS = 300
EMOTION_CACHE_MAX_SIZE = 128


class EmotionService:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, EmotionAnalysisOutput]] = {}

    async def analyze(
        self,
        user_message: str,
        recent_messages: list[dict[str, str]],
        last_emotion: str = "neutral",
    ) -> EmotionAnalysisOutput:
        message_id = f"msg_{uuid4().hex[:8]}"
        last_assistant = self._get_last_assistant_message(recent_messages)
        cached = self._get_cached(user_message)
        if cached is not None:
            cached.message_id = message_id
            return cached

        rule_based = self._rule_based_emotion(message_id, user_message)
        if rule_based is not None:
            self._set_cached(user_message, rule_based)
            return rule_based

        if not settings.dashscope_api_key:
            return self._fallback_emotion(message_id, user_message)

        user_prompt = EMOTION_SINGLE_USER_PROMPT_TEMPLATE.format(
            message_id=message_id,
            session_id="",
            user_message=user_message,
            last_assistant_message=last_assistant,
        )

        try:
            with perf_span("llm.emotion.invoke", model=emotion_llm.model, chars=len(user_message)):
                result = await asyncio.to_thread(
                    emotion_llm.chat_json,
                    EMOTION_SINGLE_SYSTEM_PROMPT,
                    user_prompt,
                    temperature=0.2,
                    max_tokens=64,
                )
            emotion = self._from_compact_result(message_id, result)
            self._set_cached(user_message, emotion)
            return emotion
        except Exception as exc:
            logger.warning("情绪分析失败，使用默认情绪结果 model=%s error=%s", emotion_llm.model, exc)
            return self._fallback_emotion(message_id, user_message)

    @staticmethod
    def _get_last_assistant_message(messages: list[dict[str, str]]) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                return str(msg.get("content", ""))
        return ""

    @staticmethod
    def _fallback_emotion(message_id: str, user_message: str) -> EmotionAnalysisOutput:
        text = user_message.strip()
        if any(word in text for word in ["不想说", "别问", "不方便", "隐私"]):
            return EmotionAnalysisOutput(
                message_id=message_id,
                primary_emotion="defensive",
                valence=-0.4,
                arousal=0.5,
                confidence=0.45,
                risk_level="medium",
                engagement_level="low",
                boundary_signal=BoundarySignal(has_refusal=True, has_privacy_concern=True),
                conversation_signal=ConversationSignal(
                    input_intent="refuse",
                    answer_quality="short_answer",
                    should_slow_down=True,
                    should_ask_follow_up=False,
                ),
                recommended_action=RecommendedAction(
                    action_type="explain_boundary", reason="用户出现拒绝或隐私边界信号"
                ),
            )
        if any(word in text for word in ["怀念", "想起来", "那时候", "以前"]):
            return EmotionAnalysisOutput(
                message_id=message_id,
                primary_emotion="nostalgia",
                confidence=0.4,
                risk_level="low",
                engagement_level="high",
                conversation_signal=ConversationSignal(
                    input_intent="continue_story",
                    answer_quality="has_story_detail",
                    should_slow_down=False,
                    should_ask_follow_up=True,
                ),
                recommended_action=RecommendedAction(
                    action_type="soft_follow_up", reason="用户正在自然回忆过去"
                ),
            )
        if len(text) <= 8:
            return EmotionAnalysisOutput(
                message_id=message_id,
                primary_emotion="apathy",
                confidence=0.35,
                risk_level="low",
                engagement_level="low",
                conversation_signal=ConversationSignal(
                    input_intent="unclear",
                    answer_quality="short_answer",
                    should_slow_down=True,
                    should_ask_follow_up=True,
                ),
                recommended_action=RecommendedAction(
                    action_type="soft_follow_up", reason="用户回复较短，建议降低问题压力"
                ),
            )
        return EmotionAnalysisOutput(
            message_id=message_id,
            primary_emotion="engagement",
            confidence=0.4,
            risk_level="low",
            engagement_level="medium",
            conversation_signal=ConversationSignal(
                input_intent="continue_story",
                answer_quality="has_fact",
                should_slow_down=False,
                should_ask_follow_up=True,
            ),
            recommended_action=RecommendedAction(
                action_type="normal_follow_up", reason="用户仍在继续讲述"
            ),
        )

    def _get_cached(self, user_message: str) -> EmotionAnalysisOutput | None:
        key = self._cache_key(user_message)
        cached = self._cache.get(key)
        if cached is None:
            return None
        created_at, emotion = cached
        if time.monotonic() - created_at > EMOTION_CACHE_TTL_SECONDS:
            self._cache.pop(key, None)
            return None
        return emotion.model_copy(deep=True)

    def _set_cached(self, user_message: str, emotion: EmotionAnalysisOutput) -> None:
        if len(self._cache) >= EMOTION_CACHE_MAX_SIZE:
            oldest = min(self._cache.items(), key=lambda item: item[1][0])[0]
            self._cache.pop(oldest, None)
        self._cache[self._cache_key(user_message)] = (time.monotonic(), emotion.model_copy(deep=True))

    @staticmethod
    def _cache_key(user_message: str) -> str:
        return " ".join(user_message.strip().lower().split())[:80]

    def _rule_based_emotion(self, message_id: str, user_message: str) -> EmotionAnalysisOutput | None:
        text = user_message.strip()
        if len(text) > 24:
            return None
        if any(word in text for word in ["不想说", "别问", "不方便", "隐私"]):
            return self._fallback_emotion(message_id, text)
        if any(word in text for word in ["怀念", "想起来", "那时候", "以前", "老家"]):
            return self._fallback_emotion(message_id, text)
        if text in {"嗯", "哦", "好", "好的", "不知道", "没想好", "可以", "行"} or len(text) <= 4:
            return self._fallback_emotion(message_id, text)
        return None

    @staticmethod
    def _from_compact_result(message_id: str, raw: dict[str, object]) -> EmotionAnalysisOutput:
        emotion = str(raw.get("emotion") or raw.get("primary_emotion") or "engagement")
        risk = str(raw.get("risk") or raw.get("risk_level") or "low")
        engagement = str(raw.get("engagement") or raw.get("engagement_level") or "medium")
        action = str(raw.get("action") or raw.get("recommended_action") or "normal_follow_up")
        slow = bool(raw.get("slow", False))
        boundary = bool(raw.get("boundary", False))
        return EmotionAnalysisOutput(
            message_id=message_id,
            primary_emotion=emotion,
            confidence=0.55,
            risk_level=risk,
            engagement_level=engagement,
            boundary_signal=BoundarySignal(
                has_refusal=boundary,
                has_privacy_concern=boundary,
            ),
            conversation_signal=ConversationSignal(
                input_intent="continue_story",
                answer_quality="has_fact",
                should_slow_down=slow,
                should_ask_follow_up=action not in {"pause", "change_topic"},
            ),
            recommended_action=RecommendedAction(action_type=action),
        )


emotion_service = EmotionService()
