import asyncio
from typing import Any

from app.core.llm_client import interview_llm
from app.services.biography_store import BiographyStore


DEFAULT_SLOTS = ["when", "where", "people", "trigger", "action", "outcome", "feeling", "meaning"]


class OutlineService:
    def __init__(self, store: BiographyStore) -> None:
        self.store = store

    async def create_draft(self, biography_id: str, highlight: str) -> dict[str, Any]:
        chapters = await self._generate_chapters(highlight)
        return self.store.save_outline(biography_id, highlight, chapters)

    async def _generate_chapters(self, highlight: str) -> list[dict[str, Any]]:
        data = await asyncio.to_thread(
            interview_llm.chat_json,
            self._outline_prompt(),
            f"高光故事：{highlight}",
            temperature=0.2,
            max_tokens=1800,
        )
        chapters = self._normalize_chapters(data.get("chapters"))
        if not chapters:
            raise ValueError("model_invalid_outline_response")
        return chapters

    @staticmethod
    def _outline_prompt() -> str:
        return (
            "你是传记采访策划。根据用户的一段高光故事，生成严格 JSON："
            "{\"chapters\":[{\"title\":\"\",\"points\":[{\"title\":\"\",\"hook\":\"\"}]}]}。"
            "生成 3 到 8 个章节，每章 1 到 3 个采集点；问题要开放、具体、适合口述。"
        )

    @classmethod
    def _normalize_chapters(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        chapters = []
        for item in value[:8]:
            if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                continue
            points = []
            raw_points = item.get("points") if isinstance(item.get("points"), list) else []
            for point in raw_points[:3]:
                if isinstance(point, dict) and str(point.get("title") or "").strip():
                    points.append({
                        "title": str(point["title"])[:80],
                        "hook": str(point.get("hook") or "")[:160],
                        "target_slots": DEFAULT_SLOTS,
                    })
            if points:
                chapters.append({"title": str(item["title"])[:80], "points": points})
        return chapters
