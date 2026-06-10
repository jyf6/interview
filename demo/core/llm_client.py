"""
LLM 客户端封装
通过 LangChain 调用阿里 DashScope（千问）模型
使用 OpenAI 兼容接口
"""

import json
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config.app_config import app_config

logger = logging.getLogger(__name__)


class LLMClient:
    """DashScope LLM 客户端"""

    def __init__(self):
        self._llm: ChatOpenAI | None = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=app_config.dashscope_model,
                api_key=app_config.dashscope_api_key,
                base_url=app_config.dashscope_base_url,
                temperature=app_config.llm_temperature,
                max_tokens=app_config.llm_max_tokens,
            )
        return self._llm

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """发送对话请求，返回文本"""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = self.llm.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        return content.strip() if isinstance(content, str) else str(content)

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        """发送对话请求，返回解析后的 JSON"""
        raw = self.chat(system_prompt, user_prompt)
        return self._parse_json(raw)

    def chat_stream(self, system_prompt: str, user_prompt: str):
        """流式对话"""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        for chunk in self.llm.stream(messages):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            if content:
                yield content

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """解析 LLM 返回的 JSON"""
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


llm_client = LLMClient()