from copy import deepcopy
from typing import Any


class ThreadStack:
    """Pure push/pop rules for a primary interview thread and diversions."""

    @staticmethod
    def push(progress: dict[str, Any], *, diversion_id: str, target: str, mention: str) -> dict[str, Any]:
        current = {
            "thread_id": str(progress.get("active_thread_id") or "primary"),
            "point_id": str(progress.get("active_point_id") or ""),
            "snapshot": deepcopy(progress.get("point_snapshot") or {}),
        }
        stack = [item for item in progress.get("thread_stack", []) if isinstance(item, dict)]
        stack.append(current)
        return {
            **progress,
            "active_thread_id": diversion_id,
            "active_point_id": f"diversion:{target}",
            "thread_stack": stack,
            "diversion": {"id": diversion_id, "target": target, "mention": mention[:200]},
            "diversion_turns": 0,
            "diversion_slots": [],
            "diversion_evaluation": {},
        }

    @staticmethod
    def pop(progress: dict[str, Any]) -> dict[str, Any]:
        stack = [item for item in progress.get("thread_stack", []) if isinstance(item, dict)]
        if not stack:
            return progress
        parent = stack.pop()
        snapshot = parent.get("snapshot") or {}
        return {
            **progress,
            **snapshot,
            "active_thread_id": parent.get("thread_id") or "primary",
            "active_point_id": parent.get("point_id") or "",
            "point_snapshot": snapshot,
            "thread_stack": stack,
            "diversion": None,
            "diversion_turns": 0,
            "diversion_messages": [],
            "diversion_slots": [],
            "diversion_evaluation": {},
        }

    @staticmethod
    def normalize(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result = []
        for item in value[-8:]:
            if not isinstance(item, dict) or not item.get("thread_id"):
                continue
            result.append({
                "thread_id": str(item["thread_id"])[:80],
                "point_id": str(item.get("point_id") or "")[:120],
                "snapshot": item.get("snapshot") if isinstance(item.get("snapshot"), dict) else {},
            })
        return result
