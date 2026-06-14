import asyncio
import logging
import re
from datetime import datetime

from app.core.config import settings
from app.core.llm_client import interview_llm
from app.core.perf import perf_span
from app.data.interview_cards import ENTRY_CARDS
from app.prompts.interview_prompts import OPENING_SYSTEM_PROMPT, RETURNING_USER_OPENING_SYSTEM_PROMPT
from app.prompts.loader import load_prompt, render_prompt
from app.schemas.interview import DialogMessage, InterviewCard

logger = logging.getLogger(__name__)


class OpeningService:
    async def build_opening_message(self, userinfo: dict[str, str] | None = None) -> DialogMessage:
        if not settings.dashscope_api_key:
            return DialogMessage(content=self._fallback_opening(userinfo))

        try:
            system_prompt = self._build_system_prompt(userinfo or {})
            with perf_span("llm.opening.invoke", model=interview_llm.model):
                raw = await asyncio.to_thread(
                    interview_llm.chat,
                    system_prompt,
                    "请直接生成开场白正文，不要输出解释。",
                    temperature=0.7,
                    max_tokens=900,
                )
            content = self._normalize_opening(raw)
            return DialogMessage(content=content or self._fallback_opening(userinfo))
        except Exception as exc:
            logger.warning("开场白生成失败，使用本地默认开场 model=%s error=%s", interview_llm.model, exc)
            return DialogMessage(content=self._fallback_opening(userinfo))

    def build_entry_cards(self) -> list[InterviewCard]:
        return [InterviewCard(**card) for card in ENTRY_CARDS]

    @staticmethod
    def _normalize_opening(raw: str) -> str:
        text = raw.strip()
        text = re.sub(r"^```(?:text)?", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
        text = re.split(r"\n\s*(?:2[\.、)]|第二[条段])\s*", text, maxsplit=1)[0].strip()
        lines = []
        for line in text.splitlines():
            cleaned = re.sub(r"^\s*(?:\d+[\.、)]|第[一二三四五六七八九十]+[条段][：:]?)\s*", "", line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n\n".join(lines[:3])[:500]

    @staticmethod
    def _build_system_prompt(userinfo: dict[str, str]) -> str:
        if not userinfo:
            return load_prompt(OPENING_SYSTEM_PROMPT)
        return render_prompt(
            RETURNING_USER_OPENING_SYSTEM_PROMPT,
            用户姓名=userinfo.get("name", ""),
            用户年龄=userinfo.get("age", ""),
            用户性别=userinfo.get("gender", ""),
            当前时间=datetime.now().isoformat(timespec="seconds"),
            上一次使用软件时间=userinfo.get("last_used_at", ""),
        )

    @staticmethod
    def _fallback_opening(userinfo: dict[str, str] | None = None) -> str:
        if userinfo:
            name = userinfo.get("name", "").strip()
            greeting = f"{name}，你回来啦。" if name else "你回来啦，又见面了。"
            return (
                f"{greeting}很高兴还能在这里遇见你，不用有压力，像和老朋友轻松聊聊就好。"
                "你可以说说近况、生活里的小事，或任何想起的过往片段；分享内容仅用于本次交流，"
                "我会认真保护隐私，你也可以自由决定说多少，不想聊的直接跳过。"
            )
        return (
            "你好呀，欢迎来到这里。接下来不用把它当成一场严肃正式的访谈，"
            "就像和一个愿意认真听你说话的朋友慢慢聊天。"
            "你可以自由决定说什么、说多少，不想回答的问题也可以直接跳过。"
            "你现在准备好开启采访了吗？"
        )
