import asyncio
import unittest
from uuid import uuid4

from app.services.biography_store import BiographyStore
from app.services.highlight_interview import HighlightInterviewService
from app.services.outline_service import OutlineService
from tests.test_thread_stack import MemoryRedis


class HighlightInterviewTest(unittest.TestCase):
    def test_outline_is_created_only_after_conversational_close(self) -> None:
        async def run() -> None:
            store = BiographyStore("postgresql://interview:interview@localhost:5432/interview")
            biography = store.create_biography()
            service = HighlightInterviewService(
                MemoryRedis(),
                OutlineService(store),
                ttl_seconds=3600,
            )
            session_id = f"highlight-test-{uuid4()}"

            started = await service.start(biography["id"], session_id)
            self.assertFalse(started["ready"])
            self.assertIsNone(started["outline"])

            first = await service.handle(session_id, "我曾经带团队完成一个很困难的项目。")
            self.assertFalse(first["ready"])
            self.assertIsNone(first["outline"])

            closed = await service.handle(session_id, "说完了")
            self.assertTrue(closed["ready"])
            self.assertIsNotNone(closed["outline"])
            self.assertEqual(closed["outline"]["biography_id"], biography["id"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
