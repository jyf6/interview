import asyncio
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import settings
from app.core.llm_client import interview_llm
from app.core.perf import perf_span
from app.prompts.loader import load_prompt, render_prompt
from app.schemas.interview import EmotionAnalysisOutput
from app.services.emotion_service import emotion_service

logger = logging.getLogger(__name__)

INTERVIEW_FALLBACK = "我已经记下来了。您愿意再多说一点当时的情景吗？"


class InterviewAgentService:
    async def generate_turn(
        self,
        user_message: str,
        recent_messages: list[dict[str, str]],
        last_emotion: str = "neutral",
    ) -> tuple[str, EmotionAnalysisOutput]:
        with perf_span("interview.turn.total", chars=len(user_message), history=len(recent_messages)):
            emotion = await emotion_service.analyze(user_message, recent_messages, last_emotion)
            reply = await self._generate_interview_reply(user_message, recent_messages, emotion)
        display = f"{reply}\n\n（{emotion.to_display_text()}）"
        return display, emotion

    async def _generate_interview_reply(
        self,
        user_message: str,
        recent_messages: list[dict[str, str]],
        emotion: EmotionAnalysisOutput,
    ) -> str:
        if not settings.dashscope_api_key:
            return INTERVIEW_FALLBACK

        user_prompt = render_prompt(
            "interview_user.txt",
            primary_emotion=emotion.primary_emotion,
            recommended_action=emotion.recommended_action.action_type,
            user_message=user_message,
        )
        messages = [SystemMessage(content=load_prompt("interview_system.txt"))]

        for msg in self._trim_messages(recent_messages, max_items=12):
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))

        messages.append(HumanMessage(content=user_prompt))

        try:
            with perf_span(
                "llm.interview.invoke",
                model=interview_llm.model,
                messages=len(messages),
                chars=len(user_message),
            ):
                response = await asyncio.to_thread(interview_llm.llm.invoke, messages)
            content = response.content if hasattr(response, "content") else str(response)
            return content.strip() if isinstance(content, str) else str(content).strip()
        except Exception as exc:
            logger.warning("LLM 采访对话失败 model=%s error=%s", interview_llm.model, exc)
            return INTERVIEW_FALLBACK

    @staticmethod
    def _trim_messages(messages: list[dict[str, str]], max_items: int) -> list[dict[str, str]]:
        allowed = []
        for item in messages[-max_items:]:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and content:
                allowed.append({"role": role, "content": content})
        return allowed
