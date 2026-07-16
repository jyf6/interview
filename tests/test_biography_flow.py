import tempfile
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.core.llm_client import interview_llm
from app.services.biography_store import BiographyStore
from app.services.outline_service import OutlineService


class BiographyFlowTest(unittest.TestCase):
    def test_creates_biography_and_versioned_outline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = BiographyStore("postgresql://interview:interview@localhost:5432/interview")
            biography = store.create_biography("interviewee-1")
            with patch.object(interview_llm, "chat_json", return_value={"chapters": [
                {"title": "童年", "points": [{"title": "记忆", "hook": "讲讲记忆"}]},
                {"title": "成长", "points": [{"title": "选择", "hook": "讲讲选择"}]},
                {"title": "工作", "points": [{"title": "突破", "hook": "讲讲突破"}]},
            ]}):
                outline = asyncio.run(OutlineService(store).create_draft(
                    biography["id"], "我最自豪的是带着团队完成了一次困难的项目。"
                ))

            self.assertEqual(outline["biography_id"], biography["id"])
            self.assertEqual(outline["version"], 1)
            self.assertEqual(outline["status"], "draft")
            self.assertEqual(len(outline["chapters"]), 3)
            self.assertTrue(all(chapter["points"] for chapter in outline["chapters"]))

    def test_outline_versions_increment_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = BiographyStore("postgresql://interview:interview@localhost:5432/interview")
            biography = store.create_biography()
            service = OutlineService(store)
            with patch.object(interview_llm, "chat_json", return_value={"chapters": [
                {"title": "成长", "points": [{"title": "选择", "hook": "讲讲选择"}]},
            ]}):
                first = asyncio.run(service.create_draft(biography["id"], "第一段高光故事内容。"))
                second = asyncio.run(service.create_draft(biography["id"], "第二段高光故事内容。"))

            self.assertEqual(first["version"], 1)
            self.assertEqual(second["version"], 2)
            self.assertEqual(store.get_outline(first["id"])["status"], "draft")

    def test_draft_can_be_edited_and_published(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = BiographyStore("postgresql://interview:interview@localhost:5432/interview")
            biography = store.create_biography()
            with patch.object(interview_llm, "chat_json", return_value={"chapters": [
                {"title": "工作", "points": [{"title": "突破", "hook": "讲讲突破"}]},
            ]}):
                outline = asyncio.run(OutlineService(store).create_draft(biography["id"], "一段高光故事内容。"))

            edited = store.replace_draft(outline["id"], [{"title": "我的工作", "points": [{"title": "第一份工作"}]}])
            published = store.publish_outline(edited["id"])

            self.assertEqual(published["status"], "published")
            self.assertEqual(published["chapters"][0]["title"], "我的工作")
            with self.assertRaises(ValueError):
                store.replace_draft(published["id"], edited["chapters"])

    def test_missing_model_configuration_is_an_error(self) -> None:
        with patch.object(settings, "dashscope_api_key", None):
            with self.assertRaisesRegex(RuntimeError, "model_unavailable"):
                interview_llm.chat("system", "user")


if __name__ == "__main__":
    unittest.main()
