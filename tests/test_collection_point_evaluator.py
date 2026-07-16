import unittest

from app.services.collection_point_evaluator import CollectionPointEvaluator


class CollectionPointEvaluatorTest(unittest.TestCase):
    def test_reports_missing_slots_and_explainable_score(self) -> None:
        evaluator = CollectionPointEvaluator()
        result = evaluator.evaluate("那年我在外地工作，因为同事帮助我，最后完成了任务，心里很高兴。")

        self.assertIn("meaning", result["missing_slots"])
        self.assertIn("when", result["covered_slots"])
        self.assertGreaterEqual(result["coverage"], 0)
        self.assertFalse(result["should_close"])

    def test_closes_after_meaning_and_required_facts_are_present(self) -> None:
        evaluator = CollectionPointEvaluator()
        result = evaluator.evaluate(
            "那年我在外地，因为机会去了单位，和同事一起坚持完成任务，最后成功了。"
            "当时天气很冷，心里很紧张，现在回头看这件事改变了我的人生。"
        )

        self.assertTrue(result["should_close"])
        self.assertTrue(evaluator.should_close(result))

    def test_user_can_close_before_threshold(self) -> None:
        evaluator = CollectionPointEvaluator()
        result = evaluator.evaluate("这件事我先不展开了。", turns=1)
        self.assertTrue(evaluator.should_close(result, user_requested_close=True))
