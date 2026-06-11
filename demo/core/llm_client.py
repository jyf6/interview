"""DashScope LLM client for the legacy demo app."""

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.app_config import app_config

logger = logging.getLogger(__name__)


class LLMClient:
    """Small OpenAI-compatible wrapper around DashScope chat models."""

    def __init__(self):
        self._llm: ChatOpenAI | None = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=app_config.dashscope_model,
                api_key=app_config.dashscope_api_key,
                base_url=app_config.dashscope_base_url.rstrip("/"),
                temperature=app_config.llm_temperature,
                max_tokens=app_config.llm_max_tokens,
                timeout=60,
                extra_body={"enable_thinking": False},
            )
        return self._llm

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = self.llm.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        return content.strip() if isinstance(content, str) else str(content)

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        raw = self.chat(system_prompt, user_prompt)
        return self._parse_json(raw)

    def chat_stream(self, system_prompt: str, user_prompt: str):
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        for chunk in self.llm.stream(messages):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            if content:
                yield content

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
            text = re.sub(r"```$", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.S)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            logger.warning("LLM JSON 解析失败，返回原文: %s", text[:200])
            return {"raw_output": text, "parse_error": True}


llm_client = LLMClient()
