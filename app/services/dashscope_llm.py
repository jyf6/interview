import asyncio
import json
import logging
import re
from typing import Any

from app.core.config import settings
from app.core.llm_client import interview_llm
from app.core.perf import perf_span
from app.data.interview_cards import ENTRY_CARDS
from app.prompts.loader import load_prompt, render_prompt

logger = logging.getLogger(__name__)


class DashScopeLLM:
    async def generate_guidance_response(
        self,
        card_id: str,
        card_corpus: dict[str, Any],
        fallback_message: str,
    ) -> dict[str, Any]:
        if not settings.dashscope_api_key:
            logger.warning("DashScope API key is not configured; using fallback response.")
            return self._fallback(fallback_message)

        user_prompt = render_prompt(
            "guidance_user.txt",
            selected_card=json.dumps(card_corpus, ensure_ascii=False),
            user_profile="{}",
            session_context='{"stage":"before_interview"}',
            card_config=json.dumps({"entry_cards": ENTRY_CARDS}, ensure_ascii=False),
            card_id=card_id,
        )
        try:
            with perf_span("llm.guidance.invoke", model=interview_llm.model, card_id=card_id):
                parsed = await asyncio.to_thread(
                    interview_llm.chat_json,
                    load_prompt("guidance_system.txt"),
                    user_prompt,
                    temperature=0.4,
                    max_tokens=512,
                )
        except Exception as exc:
            logger.warning("DashScope guidance generation failed model=%s error=%s", interview_llm.model, exc)
            return self._fallback(fallback_message)

        if parsed.get("parse_error"):
            logger.warning("DashScope guidance response is not valid JSON: %s", parsed.get("raw_output", "")[:1000])
            reparsed = self._parse_json(str(parsed.get("raw_output", "")))
            if reparsed is None:
                return self._fallback(fallback_message)
            parsed = reparsed

        assistant_message = str(parsed.get("assistant_message") or fallback_message).strip()
        recommended_next_state = parsed.get("recommended_next_state")
        if recommended_next_state not in {"GUIDANCE_CARD", "READY_TO_INTERVIEW"}:
            recommended_next_state = "GUIDANCE_CARD"

        next_cards = parsed.get("next_cards")
        if not isinstance(next_cards, list) or not next_cards:
            next_cards = ENTRY_CARDS

        return {
            "assistant_message": assistant_message[:120],
            "next_cards": next_cards,
            "recommended_next_state": recommended_next_state,
            "response_source": "llm",
        }

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any] | None:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.S)
            if match is None:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _fallback(message: str) -> dict[str, Any]:
        return {
            "assistant_message": message[:120],
            "next_cards": ENTRY_CARDS,
            "recommended_next_state": "GUIDANCE_CARD",
            "response_source": "fallback",
        }
