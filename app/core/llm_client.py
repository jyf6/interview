import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    _instances: dict[str, "LLMClient"] = {}

    def __init__(self, model: str | None = None, extra_body: dict[str, object] | None = None):
        self._model = model or settings.dashscope_model
        self._extra_body = extra_body
        self._llms: dict[tuple[float, int], ChatOpenAI] = {}

    @property
    def model(self) -> str:
        return self._model

    def get_llm(self, *, temperature: float = 0.7, max_tokens: int = 1024) -> ChatOpenAI:
        cache_key = (temperature, max_tokens)
        if cache_key not in self._llms:
            self._llms[cache_key] = ChatOpenAI(
                model=self._model,
                api_key=settings.dashscope_api_key,
                base_url=settings.dashscope_base_url,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=self._extra_body,
            )
        return self._llms[cache_key]

    @property
    def llm(self) -> ChatOpenAI:
        return self.get_llm()

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = self.get_llm(temperature=temperature, max_tokens=max_tokens).invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        return content.strip() if isinstance(content, str) else str(content)

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> dict:
        raw = self.chat(
            system_prompt,
            user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            text = text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM JSON 解析失败，返回原文: %s", text[:200])
            return {"raw_output": text, "parse_error": True}


interview_llm = LLMClient(model=settings.dashscope_interview_model)
emotion_llm = LLMClient(
    model=settings.dashscope_emotion_model,
    extra_body={"enable_thinking": False},
)
