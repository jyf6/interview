import logging
from datetime import datetime

from app.core.llm_client import interview_llm
from app.data.interview_cards import ENTRY_CARDS
from app.prompts.interview_prompts import OPENING_SYSTEM_PROMPT, RETURNING_USER_OPENING_SYSTEM_PROMPT
from app.prompts.loader import load_prompt, render_prompt
from app.schemas.interview import InterviewCard

logger = logging.getLogger(__name__)


class OpeningService:
    async def build_opening_stream(self, userinfo: dict[str, str] | None = None):
        """流式生成开场白，返回异步 token 生成器。"""
        system_prompt = self._build_system_prompt(userinfo or {})
        stream = await interview_llm.chat_stream(
            system_prompt,
            "请直接生成开场白正文，不要输出解释。",
            temperature=0.7,
            max_tokens=900,
        )

        async def token_generator():
            async for chunk in stream:
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if isinstance(token, str) and token:
                    yield token

        return token_generator()

    def build_entry_cards(self) -> list[InterviewCard]:
        return [InterviewCard(**card) for card in ENTRY_CARDS]

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
