import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import settings
from app.core.llm_client import interview_llm
from app.core.perf import perf_span
from app.schemas.interview import EmotionAnalysisOutput
from app.services.emotion_service import emotion_service

logger = logging.getLogger(__name__)

INTERVIEW_SYSTEM_PROMPT = """你是一个面向银发用户的传记采访助手，正在进行一场温和的采访对话。

你的职责：
1. 以采访的语气自然对话，像一位有耐心的倾听者。
2. 根据用户讲述的内容，温和地引导用户补充更多细节。
3. 问题要简单、具体、容易回答。不要问需要长篇大论的问题。
4. 不要评价用户、不要纠正用户、不要说教。
5. 当用户表达充分后，自然过渡到下一个相关话题。
6. 语气温和、尊重、有陪伴感。
7. 每次只问一个问题，不要连续发问。"""

INTERVIEW_FALLBACK = "您说的这些很有意思，能再多说一点吗？"


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
            return "我已经记下了。您愿意再多说一点当时的情景吗？"

        interview_context = (
            f"当前采访主题：用户的人生经历\n"
            f"用户最近表达的情绪：{emotion.primary_emotion}\n\n"
            f"请根据对话历史，生成下一句采访问题或回应。要求：\n"
            f"- 如果用户刚分享了重要经历，先温和回应，再自然提出一个补充问题。\n"
            f"- 如果用户回复较简短，尝试从不同角度引导展开。\n"
            f"- 保持对话自然流动，不要像在填表。"
        )

        messages = [SystemMessage(content=INTERVIEW_SYSTEM_PROMPT)]

        for msg in self._trim_messages(recent_messages, max_items=12):
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))

        messages.append(
            HumanMessage(content=f"{interview_context}\n\n用户最新输入：{user_message}")
        )

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
