import asyncio
import json
import logging

from app.core.config import settings
from app.core.llm_client import interview_llm
from app.core.perf import perf_span
from app.data.interview_cards import ENTRY_CARDS
from app.prompts.loader import load_prompt, render_prompt
from app.schemas.interview import DialogMessage, InterviewCard

logger = logging.getLogger(__name__)


class OpeningService:
    async def build_opening_message(self) -> DialogMessage:
        if not settings.dashscope_api_key:
            return DialogMessage(content=self._fallback_opening())

        user_prompt = render_prompt(
            "opening_user.txt",
            user_profile=json.dumps(
                {
                    "nickname": "",
                    "age_range": "",
                    "known_life_stage": [],
                    "communication_preference": "温和、慢节奏",
                    "avoid_topics": [],
                },
                ensure_ascii=False,
            ),
            session_context=json.dumps(
                {
                    "is_first_visit": True,
                    "last_state": "INIT",
                    "last_story_summary": "",
                    "unfinished_slots": [],
                    "last_emotion": "neutral",
                    "days_since_last_visit": 0,
                },
                ensure_ascii=False,
            ),
            business_context=json.dumps(
                {
                    "product_role": "传记记录助手",
                    "tone": "温和、尊重、像采访者",
                    "max_opening_sentences": 3,
                },
                ensure_ascii=False,
            ),
        )

        try:
            with perf_span("llm.opening.invoke", model=interview_llm.model):
                result = await asyncio.to_thread(
                    interview_llm.chat_json,
                    load_prompt("opening_system.txt"),
                    user_prompt,
                    temperature=0.4,
                    max_tokens=512,
                )
            content = self._compose_opening(result)
            return DialogMessage(content=content or self._fallback_opening())
        except Exception as exc:
            logger.warning("开场白生成失败，使用本地默认开场 model=%s error=%s", interview_llm.model, exc)
            return DialogMessage(content=self._fallback_opening())

    def build_entry_cards(self) -> list[InterviewCard]:
        return [InterviewCard(**card) for card in ENTRY_CARDS]

    @staticmethod
    def _compose_opening(result: dict[str, object]) -> str:
        if result.get("parse_error"):
            return ""
        parts = [
            str(result.get("main_message") or "").strip(),
            str(result.get("trust_sentence") or "").strip(),
            str(result.get("micro_question") or "").strip(),
        ]
        content = "".join(part for part in parts if part)
        return content[:220]

    @staticmethod
    def _fallback_opening() -> str:
        return (
            "您好，我会像一位安静的记录者，陪您把重要经历慢慢整理下来。"
            "这里没有标准答案，您想到哪里，我们就从哪里开始。"
            "可以先从一个人、一个地方，或一件现在还记得的小事说起。"
        )
