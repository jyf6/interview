import asyncio
import logging

from app.core.config import settings
from app.core.llm_client import interview_llm
from app.core.perf import perf_span
from app.prompts.interview_prompts import GUIDANCE_QA_SYSTEM_PROMPT
from app.prompts.loader import load_prompt

logger = logging.getLogger(__name__)


class DashScopeLLM:
    async def generate_guidance_response(
        self,
        card_id: str,
        selected_text: str,
    ) -> dict[str, str]:
        user_selection = selected_text.strip() or "我还不知道该怎么开始这次采访"
        if not settings.dashscope_api_key:
            logger.warning("DashScope API key is not configured; using fallback response.")
            return self._fallback(self._fallback_guidance(user_selection))

        try:
            with perf_span("llm.guidance.invoke", model=interview_llm.model, card_id=card_id):
                raw = await asyncio.to_thread(
                    interview_llm.chat,
                    load_prompt(GUIDANCE_QA_SYSTEM_PROMPT),
                    f"用户选择或输入的内容：{user_selection}\n请只输出 80 到 100 字左右的回答正文。",
                    temperature=0.4,
                    max_tokens=512,
                )
        except Exception as exc:
            logger.warning("DashScope guidance generation failed model=%s error=%s", interview_llm.model, exc)
            return self._fallback(self._fallback_guidance(user_selection))

        assistant_message = str(raw).strip() or self._fallback_guidance(user_selection)
        return {
            "assistant_message": assistant_message[:180],
            "response_source": "llm",
        }

    @staticmethod
    def _fallback_guidance(user_selection: str) -> str:
        return (
            "不用紧张，我们可以按你的节奏慢慢来。你刚刚提到的感受我已经知道了，"
            "接下来不需要准备完整答案，也不用按时间顺序说。先从你最容易想起的一点开始，"
            "我会一边听一边帮你整理。"
        )

    @staticmethod
    def _fallback(message: str) -> dict[str, str]:
        return {
            "assistant_message": message[:180],
            "response_source": "fallback",
        }
