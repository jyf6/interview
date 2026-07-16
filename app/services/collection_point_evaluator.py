from typing import Any


DEFAULT_SLOTS = (
    "when",
    "where",
    "people",
    "trigger",
    "action",
    "outcome",
    "sensory_detail",
    "feeling",
    "meaning",
)


class CollectionPointEvaluator:
    """Small, explainable coverage evaluator for one story thread."""

    SLOT_MARKERS = {
        "when": ("那年", "当时", "后来", "岁", "年", "月", "天"),
        "where": ("在", "地方", "家里", "学校", "单位", "外地"),
        "people": ("父母", "家人", "老师", "同事", "朋友", "我们", "他", "她"),
        "trigger": ("因为", "起因", "决定", "遇到", "问题", "机会"),
        "action": ("于是", "然后", "开始", "做了", "去了", "坚持", "选择"),
        "outcome": ("最后", "结果", "终于", "成功", "失败", "后来"),
        "sensory_detail": ("看见", "听见", "味道", "声音", "天气", "眼泪", "笑"),
        "feeling": ("觉得", "心里", "害怕", "高兴", "难过", "紧张", "放心"),
        "meaning": ("影响", "明白", "学会", "改变", "现在回头", "意义", "人生"),
    }

    def __init__(self, required_slots: list[str] | None = None, threshold: float = 0.75) -> None:
        self.required_slots = tuple(slot for slot in (required_slots or list(DEFAULT_SLOTS)) if slot in DEFAULT_SLOTS)
        self.threshold = threshold

    def extract_slots(self, text: str, existing: list[str] | None = None) -> list[str]:
        covered = set(existing or [])
        for slot in self.required_slots:
            if any(marker in text for marker in self.SLOT_MARKERS[slot]):
                covered.add(slot)
        return [slot for slot in self.required_slots if slot in covered]

    def evaluate(self, text: str, covered_slots: list[str] | None = None, *, turns: int = 0) -> dict[str, Any]:
        covered = self.extract_slots(text, covered_slots)
        missing = [slot for slot in self.required_slots if slot not in covered]
        factual = set(("when", "where", "people", "trigger", "action", "outcome"))
        facts_score = len(factual.intersection(covered)) / len(factual)
        detail_score = 1.0 if "sensory_detail" in covered else 0.0
        meaning_score = 1.0 if {"feeling", "meaning"}.intersection(covered) else 0.0
        score = round(facts_score * 0.6 + detail_score * 0.15 + meaning_score * 0.25, 3)
        return {
            "coverage": score,
            "covered_slots": covered,
            "missing_slots": missing,
            "turns": turns,
            "meaning_ready": "meaning" in covered,
            "should_close": score >= self.threshold and "meaning" in covered,
        }

    def should_close(self, evaluation: dict[str, Any], *, user_requested_close: bool = False, max_turns: int = 6) -> bool:
        if user_requested_close or evaluation.get("should_close"):
            return True
        # A turn limit prevents an endless interview, but only after a minimally useful story exists.
        return bool(
            evaluation.get("turns", 0) >= max_turns
            and float(evaluation.get("coverage", 0)) >= 0.45
        )
