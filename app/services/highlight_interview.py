import json
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis

from app.services.collection_point_evaluator import CollectionPointEvaluator
from app.services.outline_service import OutlineService


class HighlightInterviewService:
    """Collect the opening highlight through a short text conversation."""

    def __init__(self, redis: Redis, outline_service: OutlineService, ttl_seconds: int) -> None:
        self.redis = redis
        self.outline_service = outline_service
        self.ttl_seconds = ttl_seconds
        self.evaluator = CollectionPointEvaluator(
            required_slots=["when", "where", "people", "trigger", "action", "outcome", "feeling", "meaning"],
            threshold=0.65,
        )

    async def start(self, biography_id: str, session_id: str | None = None) -> dict[str, Any]:
        if not self.outline_service.store.biography_exists(biography_id):
            raise KeyError("biography_not_found")
        session_id = session_id or f"highlight:{biography_id}:{uuid4()}"
        state = await self._load(session_id)
        if state and state.get("biography_id") != biography_id:
            raise ValueError("biography_id_mismatch")
        if not state:
            assistant = "先从一段让您最自豪、最难忘，或最想留下来的经历说起。那件事发生了什么？"
            state = {
                "biography_id": biography_id,
                "messages": [{"role": "assistant", "content": assistant}],
                "turns": 0,
                "slots": [],
                "evaluation": {},
                "completed": False,
                "outline": None,
            }
            await self._save(session_id, state)
        return self._response(
            session_id,
            state,
            state["messages"][-1]["content"] if state["messages"] else "我们开始吧。",
        )

    async def handle(self, session_id: str, content: str) -> dict[str, Any]:
        state = await self._load(session_id)
        if not state:
            raise KeyError("highlight_session_not_found")
        if state.get("completed"):
            return self._response(session_id, state, "这段高光故事已经收集完成，可以继续编辑大纲。")

        text = content.strip()
        if not text:
            return self._response(session_id, state, "您可以先用一两句话讲讲那段经历。")
        messages = [*state.get("messages", []), {"role": "user", "content": text}]
        turns = int(state.get("turns", 0)) + 1
        combined = "\n".join(item["content"] for item in messages)
        slots = self.evaluator.extract_slots(combined, state.get("slots", []))
        evaluation = self.evaluator.evaluate(combined, slots, turns=turns)
        requested_close = any(token in text for token in ("\u8bf4\u5b8c\u4e86", "\u6ca1\u6709\u4e86", "\u5c31\u8fd9\u4e9b", "\u5dee\u4e0d\u591a"))
        should_close = requested_close or (
            turns >= 2 and evaluation["coverage"] >= 0.65 and evaluation["meaning_ready"]
        )

        if should_close:
            highlight = "\n".join(item["content"] for item in messages)
            outline = await self.outline_service.create_draft(str(state["biography_id"]), highlight)
            assistant = "这段经历已经足够形成一份专属大纲了。我先生成草稿，您可以继续编辑章节和采集点。"
            state.update({
                "messages": [*messages, {"role": "assistant", "content": assistant}],
                "turns": turns,
                "slots": slots,
                "evaluation": evaluation,
                "completed": True,
                "outline": outline,
            })
        else:
            prompts = {
                "when": "这件事大概发生在什么时候？",
                "where": "当时是在什么地方？",
                "people": "那时还有哪些人和您一起经历？",
                "trigger": "事情是因为什么开始的？",
                "action": "接下来具体发生了什么？",
                "outcome": "最后结果怎么样？",
                "feeling": "那一刻您心里是什么感受？",
                "meaning": "这件事后来对您的人生产生了什么影响？",
            }
            assistant = prompts.get((evaluation.get("missing_slots") or ["meaning"])[0], "您还愿意再讲讲这段经历中的一个细节吗？")
            state.update({
                "messages": [*messages, {"role": "assistant", "content": assistant}],
                "turns": turns,
                "slots": slots,
                "evaluation": evaluation,
            })
        await self._save(session_id, state)
        return self._response(session_id, state, assistant)

    async def belongs_to(self, session_id: str, biography_id: str) -> bool:
        state = await self._load(session_id)
        return bool(state and state.get("biography_id") == biography_id)

    async def _load(self, session_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(self._key(session_id))
        if not raw:
            return None
        return json.loads(raw)

    async def _save(self, session_id: str, state: dict[str, Any]) -> None:
        await self.redis.set(self._key(session_id), json.dumps(state, ensure_ascii=False), ex=self.ttl_seconds)

    @staticmethod
    def _key(session_id: str) -> str:
        return f"interview:highlight:{session_id}"

    @staticmethod
    def _response(session_id: str, state: dict[str, Any], assistant: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "assistant_message": assistant,
            "messages": state.get("messages", []),
            "ready": bool(state.get("completed")),
            "outline": state.get("outline"),
            "evaluation": state.get("evaluation") or {},
        }
