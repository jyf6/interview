import asyncio
import json
from urllib import error, request

from app.core.config import settings
from app.schemas.agent import AgentMessageRead


class LLMServiceError(RuntimeError):
    pass


class DashScopeChatService:
    async def generate_reply(self, messages: list[AgentMessageRead], goal: str) -> str:
        if not settings.dashscope_api_key:
            raise LLMServiceError("DASHSCOPE_API_KEY is not configured.")

        payload = {
            "model": settings.dashscope_model,
            "messages": self._build_messages(messages, goal),
        }
        return await asyncio.to_thread(self._request_completion, payload)

    def _build_messages(self, messages: list[AgentMessageRead], goal: str) -> list[dict[str, str]]:
        system_prompt = settings.dashscope_system_prompt
        if goal:
            system_prompt = f"{system_prompt}\n\nCurrent session goal: {goal}"

        chat_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for message in messages:
            if message.role not in {"system", "user", "assistant"}:
                continue
            chat_messages.append({"role": message.role, "content": message.content})
        return chat_messages

    def _request_completion(self, payload: dict[str, object]) -> str:
        endpoint = f"{settings.dashscope_base_url.rstrip('/')}/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {settings.dashscope_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=settings.dashscope_timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMServiceError(
                f"DashScope request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except error.URLError as exc:
            raise LLMServiceError(f"DashScope request failed: {exc.reason}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMServiceError("DashScope returned a non-JSON response.") from exc

        choices = data.get("choices")
        if not choices:
            raise LLMServiceError("DashScope returned no choices.")

        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

        if isinstance(content, list):
            text_parts = [
                item["text"]
                for item in content
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
            ]
            if text_parts:
                return "\n".join(text_parts).strip()

        raise LLMServiceError("DashScope response did not include assistant content.")
