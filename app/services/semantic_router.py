from typing import Literal

from pydantic import BaseModel, Field


SemanticRouteName = Literal[
    "normal_interview",
    "cross_topic_event",
    "resistance_turn",
    "skip",
    "implicit_low_engagement",
]


class SemanticRoute(BaseModel):
    route: SemanticRouteName = "normal_interview"
    target_stage_id: str | None = None
    event_scope: Literal["none", "bounded_event"] = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class UnifiedSemanticRouter:
    """Deterministic pre-router; an LLM router can replace only this class later."""

    STAGE_KEYWORDS = {
        "S1": ("童年", "小时候", "父母", "家里"),
        "S2": ("上学", "学校", "青春", "大学", "老师"),
        "S3": ("第一份工作", "刚工作", "职场", "上班"),
        "S4": ("转行", "创业", "转折", "破局"),
        "S5": ("巅峰", "低谷", "成就", "事业"),
        "S6": ("家庭", "孩子", "取舍", "陪伴"),
        "S7": ("退休", "传承", "晚年", "以后"),
    }
    EVENT_MARKERS = ("一次", "那年", "当时", "后来", "经历", "发生", "记得")

    @classmethod
    def classify_outline(
        cls,
        content: str,
        current_point_id: str,
        points: list[dict[str, str]],
    ) -> SemanticRoute:
        """Prefer generated collection-point titles when routing a diversion."""
        base = cls.classify(content, current_point_id)
        text = content.strip()
        if base.route in {"resistance_turn", "skip", "implicit_low_engagement"} or len(text) < 12:
            return base
        for point in points:
            point_id = str(point.get("id") or "")
            title = str(point.get("title") or "").strip()
            if point_id and point_id != current_point_id and len(title) >= 2 and title in text:
                if any(marker in text for marker in cls.EVENT_MARKERS):
                    return SemanticRoute(
                        route="cross_topic_event",
                        target_stage_id=point_id,
                        event_scope="bounded_event",
                        confidence=0.9,
                        reason="outline_point_match",
                    )
        return base

    @classmethod
    def classify(cls, content: str, current_stage_id: str) -> SemanticRoute:
        text = content.strip()
        if not text:
            return SemanticRoute(route="implicit_low_engagement", confidence=1.0, reason="空输入")
        if any(token in text for token in ("跳过", "不想说", "别问了", "换个话题")):
            return SemanticRoute(route="resistance_turn", confidence=0.95, reason="用户明确拒绝当前话题")
        if text in {"算了", "先不说", "跳过"}:
            return SemanticRoute(route="skip", confidence=0.98, reason="用户主动跳过")
        if len(text) < 8:
            return SemanticRoute(route="implicit_low_engagement", confidence=0.8, reason="回答过短")

        target = next(
            (stage_id for stage_id, words in cls.STAGE_KEYWORDS.items()
             if stage_id != current_stage_id and any(word in text for word in words)),
            None,
        )
        if target and len(text) >= 20 and any(marker in text for marker in cls.EVENT_MARKERS):
            return SemanticRoute(
                route="cross_topic_event",
                target_stage_id=target,
                event_scope="bounded_event",
                confidence=0.86,
                reason="出现跨阶段且具备事件边界的叙述",
            )
        return SemanticRoute(reason="未发现明确的跨阶段完整事件")
