import unittest
import asyncio
import tempfile
from pathlib import Path
from uuid import uuid4

from app.schemas.interview import DialogTextRequest, ThreadCommandRequest
from app.services.interview_state_machine import InterviewStateMachine
from app.services.biography_store import BiographyStore
from app.services.thread_stack import ThreadStack


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.lists.pop(key, None)

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.lists.get(key, [])
        return values[start:] if end == -1 else values[start : end + 1]


class ThreadStackTest(unittest.TestCase):
    def test_push_then_pop_restores_primary_point(self) -> None:
        primary = {
            "active_thread_id": "primary",
            "active_point_id": "childhood-memory",
            "point_snapshot": {"phase": "fact", "missing": ["where"]},
        }

        diversion = ThreadStack.push(primary, diversion_id="event-1", target="first-job", mention="第一次工作时的经历")
        resumed = ThreadStack.pop(diversion)

        self.assertEqual(diversion["active_thread_id"], "event-1")
        self.assertEqual(len(diversion["thread_stack"]), 1)
        self.assertEqual(resumed["active_thread_id"], "primary")
        self.assertEqual(resumed["active_point_id"], "childhood-memory")
        self.assertEqual(resumed["point_snapshot"]["missing"], ["where"])
        self.assertEqual(resumed["thread_stack"], [])

    def test_pop_without_parent_is_noop(self) -> None:
        progress = {"active_thread_id": "primary", "thread_stack": []}
        self.assertEqual(ThreadStack.pop(progress), progress)

    def test_state_machine_persists_and_restores_thread_stack(self) -> None:
        async def run() -> None:
            machine = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            session_id = "thread-command-session"
            progress = await machine._get_or_create_interview_progress(session_id)
            progress["active_point_id"] = "childhood-memory"
            progress["point_snapshot"] = {"phase": "fact"}
            await machine._set_interview_progress(session_id, progress)

            pushed = await machine.handle_thread_command(ThreadCommandRequest(
                session_id=session_id, command="push", diversion_id="event-1", target="first-job", mention="第一份工作"
            ))
            self.assertEqual(pushed.state_interview["active_thread_id"], "event-1")
            self.assertEqual(len(pushed.state_interview["thread_stack"]), 1)

            popped = await machine.handle_thread_command(ThreadCommandRequest(session_id=session_id, command="pop"))
            self.assertEqual(popped.state_interview["active_thread_id"], "primary")
            self.assertEqual(popped.state_interview["active_point_id"], "childhood-memory")

        asyncio.run(run())

    def test_text_turn_auto_pushes_and_closes_bounded_diversion(self) -> None:
        async def run() -> None:
            machine = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            session_id = "auto-diversion-session"
            first = await machine.handle_dialog_text(DialogTextRequest(
                session_id=session_id,
                content="后来我讲到第一份工作，那次在外地遇到困难，最后还是坚持完成了任务。",
            ))
            self.assertEqual(first.state_interview["active_thread_id"].startswith("diversion:"), True)
            self.assertEqual(first.state_interview["diversion"]["target"], "S3")

            closed = await machine.handle_dialog_text(DialogTextRequest(session_id=session_id, content="说完了。"))
            self.assertEqual(closed.state_interview["active_thread_id"], "primary")
            self.assertIsNone(closed.state_interview["diversion"])

        asyncio.run(run())

    def test_closed_diversion_is_archived(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as directory:
                store = BiographyStore("postgresql://interview:interview@localhost:5432/interview")
                machine = InterviewStateMachine(MemoryRedis(), store)  # type: ignore[arg-type]
                session_id = "archive-session"
                await machine.handle_dialog_text(DialogTextRequest(
                    session_id=session_id,
                    content="后来我讲到第一份工作，那次在外地遇到困难，最后还是坚持完成了任务。",
                ))
                await machine.handle_dialog_text(DialogTextRequest(session_id=session_id, content="说完了。"))
                materials = store.list_materials(session_id)
                self.assertEqual(len(materials), 1)
                self.assertEqual(materials[0]["target_stage_id"], "S3")
                self.assertIn("第一份工作", materials[0]["content"])

        asyncio.run(run())

    def test_published_outline_starts_session_at_first_collection_point(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as directory:
                store = BiographyStore("postgresql://interview:interview@localhost:5432/interview")
                biography = store.create_biography()
                outline = store.save_outline(
                    biography["id"],
                    "高光故事",
                    [{"title": "工作", "points": [{"title": "第一份工作", "hook": "您还记得第一份工作吗？"}]}],
                )
                outline = store.publish_outline(outline["id"])
                machine = InterviewStateMachine(MemoryRedis(), store)  # type: ignore[arg-type]
                response = await machine.start_outline_session(
                    "outline-session", biography["id"], outline["id"]
                )

                self.assertEqual(response.current_state, "INTERVIEWING")
                self.assertEqual(response.state_interview["outline_id"], outline["id"])
                self.assertEqual(response.state_interview["active_point"]["title"], "第一份工作")

        asyncio.run(run())

    def test_complete_point_unlocks_next_published_point(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as directory:
                store = BiographyStore("postgresql://interview:interview@localhost:5432/interview")
                biography = store.create_biography()
                outline = store.save_outline(
                    biography["id"], "高光故事", [{"title": "工作", "points": [
                        {"title": "第一份工作", "hook": "先聊第一份工作。"},
                        {"title": "关键突破", "hook": "再聊一次关键突破。"},
                    ]}],
                )
                store.publish_outline(outline["id"])
                machine = InterviewStateMachine(MemoryRedis(), store)  # type: ignore[arg-type]
                await machine.start_outline_session("point-session", biography["id"], outline["id"])
                response = await machine.handle_thread_command(ThreadCommandRequest(
                    session_id="point-session", command="complete_point"
                ))
                self.assertEqual(response.state_interview["active_point"]["title"], "关键突破")

        asyncio.run(run())

    def test_outline_text_turn_closes_and_archives_complete_story(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as directory:
                store = BiographyStore("postgresql://interview:interview@localhost:5432/interview")
                biography = store.create_biography()
                outline = store.save_outline(
                    biography["id"],
                    "highlight",
                    [{"title": "work", "points": [{"title": "first job", "hook": "tell me about it"}]}],
                )
                store.publish_outline(outline["id"])
                machine = InterviewStateMachine(MemoryRedis(), store)  # type: ignore[arg-type]
                session_id = f"dynamic-session-{uuid4()}"
                await machine.start_outline_session(session_id, biography["id"], outline["id"])
                content = (
                    "2010\u5e74\u5728\u5355\u4f4d\u548c\u540c\u4e8b\u4e00\u8d77\uff0c\u56e0\u4e3a\u4e00\u4e2a\u673a\u4f1a\uff0c"
                    "\u4e8e\u662f\u5f00\u59cb\u505a\u4e86\u9879\u76ee\uff0c\u6700\u540e\u6210\u529f\uff0c"
                    "\u6211\u89c9\u5f97\u8fd9\u6539\u53d8\u4e86\u6211\u7684\u4eba\u751f\u3002"
                )
                response = await machine.handle_dialog_text(
                    DialogTextRequest(session_id=session_id, content=content)
                )
                self.assertEqual(response.state_interview["completed"], 1)
                self.assertEqual(len(store.list_materials(session_id)), 1)

        asyncio.run(run())
