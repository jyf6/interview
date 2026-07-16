import unittest

from app.services.semantic_router import UnifiedSemanticRouter


class SemanticRouterTest(unittest.TestCase):
    def test_routes_bounded_cross_topic_event(self) -> None:
        result = UnifiedSemanticRouter.classify(
            "后来我讲到第一份工作，那次在外地遇到困难，最后还是坚持完成了任务。",
            "S1",
        )
        self.assertEqual(result.route, "cross_topic_event")
        self.assertEqual(result.target_stage_id, "S3")
        self.assertEqual(result.event_scope, "bounded_event")

    def test_does_not_interrupt_for_broad_reference(self) -> None:
        result = UnifiedSemanticRouter.classify("我以前也工作过。", "S1")
        self.assertEqual(result.route, "normal_interview")

    def test_resistance_has_priority(self) -> None:
        result = UnifiedSemanticRouter.classify("我不想说工作，换个话题吧。", "S1")
        self.assertEqual(result.route, "resistance_turn")

    def test_outline_router_prefers_generated_point_id(self) -> None:
        result = UnifiedSemanticRouter.classify_outline(
            "\u540e\u6765\u6211\u8bb2\u5230\u5357\u65b9\u521b\u4e1a\uff0c\u90a3\u6b21\u7ecf\u5386\u5f88\u96be\u5fd8\u3002",
            "point-childhood",
            [
                {"id": "point-childhood", "title": "童年"},
                {"id": "point-startup", "title": "南方创业"},
            ],
        )
        self.assertEqual(result.route, "cross_topic_event")
        self.assertEqual(result.target_stage_id, "point-startup")
