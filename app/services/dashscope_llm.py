import asyncio

from app.core.llm_client import interview_llm
from app.core.perf import perf_span
from app.prompts.interview_prompts import GUIDANCE_QA_SYSTEM_PROMPT
from app.prompts.loader import load_prompt


class DashScopeLLM:
    async def generate_guidance_response(
        self,
        card_id: str,
        selected_text: str,
    ) -> dict[str, str]:
        user_selection = selected_text.strip()
        if not user_selection:
            raise ValueError("guidance_input_required")
        with perf_span("llm.guidance.invoke", model=interview_llm.model, card_id=card_id):
            raw = await asyncio.to_thread(
                interview_llm.chat,
                load_prompt(GUIDANCE_QA_SYSTEM_PROMPT),
                f"用户选择或输入的内容：{user_selection}\n请只输出 80 到 100 字左右的回答正文。",
                temperature=0.4,
                max_tokens=512,
            )
        return {
            "assistant_message": raw[:180],
            "response_source": "llm",
        }
