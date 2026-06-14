import asyncio
import logging
from typing import Any

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
        card_corpus: dict[str, Any],
        fallback_message: str,
        question: str | None = None,
    ) -> dict[str, Any]:
        user_question = question or str(card_corpus.get("card_label") or fallback_message)
        if not settings.dashscope_api_key:
            logger.warning("DashScope API key is not configured; using fallback response.")
            return self._fallback(self._fallback_guidance(user_question))

        try:
            with perf_span("llm.guidance.invoke", model=interview_llm.model, card_id=card_id):
                raw = await asyncio.to_thread(
                    interview_llm.chat,
                    load_prompt(GUIDANCE_QA_SYSTEM_PROMPT),
                    f"用户的问题或疑惑：{user_question}\n请只输出80到100字的回答正文。",
                    temperature=0.4,
                    max_tokens=512,
                )
        except Exception as exc:
            logger.warning("DashScope guidance generation failed model=%s error=%s", interview_llm.model, exc)
            return self._fallback(self._fallback_guidance(user_question))

        assistant_message = str(raw).strip() or self._fallback_guidance(user_question)

        return {
            "assistant_message": assistant_message[:180],
            "response_source": "llm",
        }

    @staticmethod
    def _fallback_guidance(question: str) -> str:
        if any(keyword in question for keyword in ["例子", "示范"]):
            return "当然可以呀。我们会参考童年成长、青春求学、人生转折、生活阅历和人生总结来聊，但你也可以想到哪里说哪里。比如童年一件小事，或人生转折里的一个决定，简单真实地说就很好。"
        if any(keyword in question for keyword in ["隐私", "不方便", "影响"]):
            return "这点你完全可以放心哦。所有内容都由你自己决定，不方便说的地方直接跳过就好，也不会影响后续流程和最终生成效果。我只记录你愿意分享的部分，轻松聊就可以。"
        if any(keyword in question for keyword in ["表达", "讲不好", "嘴笨"]):
            return "别担心呀，这里没有标准答案，也不会评判你说得好不好。简单几句、零碎回忆都可以，想到哪里说哪里，不用刻意按顺序。我会认真听，跟着你的节奏慢慢聊。"
        if any(keyword in question for keyword in ["描述", "说什么", "从哪里"]):
            return "不用刻意组织语言哦。你只要分享真实经历、细碎回忆，或此刻想到的感受就好。想到哪里说哪里，顺序完全由你决定，长短都没关系，真实就是最好的。"
        return "不用紧张呀。采访会参考童年成长、青春求学、人生转折、生活阅历和人生总结这五个方向，但全程就是轻松一问一答。想到哪里说哪里，顺序由你掌控，没有复杂流程，也没有时间压力。"

    @staticmethod
    def _fallback(message: str) -> dict[str, Any]:
        return {
            "assistant_message": message[:180],
            "response_source": "fallback",
        }
