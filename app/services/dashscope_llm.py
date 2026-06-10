import json
import logging
import re
from typing import Any

import httpx

from app.core.config import settings
from app.data.interview_cards import ENTRY_CARDS

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

        prompt = self._build_prompt(card_id, card_corpus)
        try:
            async with httpx.AsyncClient(timeout=settings.dashscope_timeout_seconds) as client:
                response = await client.post(
                    f"{settings.dashscope_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.dashscope_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.dashscope_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": settings.dashscope_system_prompt,
                            },
                            {
                                "role": "user",
                                "content": prompt,
                            },
                        ],
                        "temperature": 0.4,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "DashScope request failed: status=%s body=%s",
                exc.response.status_code,
                exc.response.text[:1000],
            )
            return self._fallback(fallback_message)
        except httpx.HTTPError as exc:
            logger.warning("DashScope request error: %s", exc)
            return self._fallback(fallback_message)

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("DashScope response schema is unexpected: error=%s body=%s", exc, response.text[:1000])
            return self._fallback(fallback_message)

        parsed = self._parse_json(content)
        if parsed is None:
            logger.warning("DashScope response is not valid JSON content: %s", content[:1000])
            return self._fallback(fallback_message)

        assistant_message = str(parsed.get("assistant_message") or fallback_message).strip()
        recommended_next_state = parsed.get("recommended_next_state")
        if recommended_next_state not in {"GUIDANCE_CARD", "READY_TO_INTERVIEW"}:
            recommended_next_state = "GUIDANCE_CARD"

        return {
            "assistant_message": assistant_message[:120],
            "next_cards": ENTRY_CARDS,
            "recommended_next_state": recommended_next_state,
            "response_source": "llm",
        }

    @staticmethod
    def _build_prompt(card_id: str, card_corpus: dict[str, Any]) -> str:
        return f"""
你是一位面向用户的传记采访引导助手。用户正在采访开始前选择了一张“顾虑/状态”卡片。
你的任务：
1. 根据卡片语料，生成一句自然、温和、低压力的安抚回应。
2. 让用户感觉可以慢慢来，不需要一次讲完整。
3. 不要假设用户年龄、职业、家庭关系、人生经历或具体创伤。
4. 不要连续追问多个问题。
5. 不要输出 Markdown，不要输出解释文字。
6. 必须输出合法 JSON。

用户选择的 card_id：{card_id}

卡片语料：{json.dumps(card_corpus, ensure_ascii=False)}

固定下一步卡片：
{json.dumps(ENTRY_CARDS, ensure_ascii=False)}

请严格按这个 JSON 格式输出：
{{
  "assistant_message": "给用户的一句安抚回应，不超过120个字",
  "next_cards": {json.dumps(ENTRY_CARDS, ensure_ascii=False)},
  "recommended_next_state": "GUIDANCE_CARD"
}}
""".strip()

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
