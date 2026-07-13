import json
import logging
import re
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, model: str | None = None, extra_body: dict[str, object] | None = None):
        self._model = model or settings.dashscope_model
        self._extra_body = extra_body
        self._llms: dict[tuple[float, int], Any] = {}

    @property
    def model(self) -> str:
        return self._model

    def get_llm(self, *, temperature: float = 0.7, max_tokens: int = 1024) -> Any:
        from langchain_openai import ChatOpenAI

        cache_key = (temperature, max_tokens)
        if cache_key not in self._llms:
            self._llms[cache_key] = ChatOpenAI(
                model=self._model,
                api_key=settings.dashscope_api_key,
                base_url=settings.dashscope_base_url.rstrip("/"),
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=settings.dashscope_timeout_seconds,
                extra_body=self._extra_body,
            )
        return self._llms[cache_key]

    @property
    def llm(self) -> Any:
        return self.get_llm()

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = self.get_llm(temperature=temperature, max_tokens=max_tokens).invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        return content.strip() if isinstance(content, str) else str(content)

    async def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> Any:
        """流式调用 LLM，返回异步生成器，逐 token 产出文本片段。"""
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        return self.get_llm(temperature=temperature, max_tokens=max_tokens).astream(messages)

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        raw = self.chat(
            system_prompt,
            user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._parse_json(raw)

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


interview_llm = LLMClient(
    model=settings.dashscope_interview_model,
    extra_body={"enable_thinking": False},
)
