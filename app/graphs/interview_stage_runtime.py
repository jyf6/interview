from typing import Any

from app.data.interview_stage_config import (
    FINAL_STAGE_TASK,
    FIRST_INTERVIEW_STAGE,
    INTERVIEW_STAGE_BY_ID,
    INTERVIEW_STAGE_IDS,
    LAST_INTERVIEW_STAGE,
    MAIN_QUESTION_IDS,
    STAGE_MAIN_QUESTION_IDS,
    STAGE_TASK_BY_REMAINING_ROUNDS,
)

SUPPLEMENT_QUESTION_ID = 9


class InterviewStageRuntime:
    """Stage-local rules shared by the parent graph and stage subgraphs."""

    @staticmethod
    def stage_id(progress: dict[str, Any]) -> str:
        stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
        return stage_id if stage_id in INTERVIEW_STAGE_BY_ID else FIRST_INTERVIEW_STAGE

    @staticmethod
    def stage_name(stage_id: Any) -> str | None:
        stage = INTERVIEW_STAGE_BY_ID.get(str(stage_id))
        return str(stage["name"]) if stage else None

    @staticmethod
    def main_question_ids_for_stage(stage_id: str | None) -> tuple[int, ...]:
        return STAGE_MAIN_QUESTION_IDS.get(str(stage_id), MAIN_QUESTION_IDS)

    @staticmethod
    def valid_main_question_id(value: Any, stage_id: str | None = None) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            question_id = int(value)
        except (TypeError, ValueError):
            return None
        if question_id == SUPPLEMENT_QUESTION_ID:
            return question_id
        return question_id if question_id in InterviewStageRuntime.main_question_ids_for_stage(stage_id) else None

    @staticmethod
    def valid_main_question_ids(value: Any, stage_id: str | None = None) -> list[int]:
        if not isinstance(value, list):
            return []
        result: list[int] = []
        for item in value:
            question_id = InterviewStageRuntime.valid_main_question_id(item, stage_id)
            if (
                question_id in InterviewStageRuntime.main_question_ids_for_stage(stage_id)
                and question_id not in result
            ):
                result.append(question_id)
        return result

    @staticmethod
    def format_main_question_ids(question_ids: list[int]) -> str:
        ids = InterviewStageRuntime.valid_main_question_ids(question_ids)
        return "无" if not ids else "、".join(str(question_id) for question_id in ids)

    @staticmethod
    def remaining_main_question_count(progress: dict[str, Any]) -> int:
        stage_id = InterviewStageRuntime.stage_id(progress)
        valid_ids = InterviewStageRuntime.main_question_ids_for_stage(stage_id)
        completed_ids = InterviewStageRuntime.valid_main_question_ids(
            progress.get("completed_main_question_ids"),
            stage_id,
        )
        return max(0, len(valid_ids) - len(completed_ids))

    @staticmethod
    def sync_main_question_progress(progress: dict[str, Any]) -> dict[str, Any]:
        stage_id = InterviewStageRuntime.stage_id(progress)
        completed_ids = InterviewStageRuntime.valid_main_question_ids(
            progress.get("completed_main_question_ids"),
            stage_id,
        )
        remaining_count = InterviewStageRuntime.remaining_main_question_count(
            {"stage_id": stage_id, "completed_main_question_ids": completed_ids}
        )
        return {
            **progress,
            "stage_id": stage_id,
            "completed_main_question_ids": completed_ids,
            "awaiting_stage_completion": 1 if remaining_count == 0 and not progress.get("completed") else 0,
        }

    @staticmethod
    def mark_active_main_question_answered(progress: dict[str, Any]) -> dict[str, Any]:
        stage_id = InterviewStageRuntime.stage_id(progress)
        active_question_id = InterviewStageRuntime.valid_main_question_id(
            progress.get("active_main_question_id"),
            stage_id,
        )
        completed_ids = InterviewStageRuntime.valid_main_question_ids(
            progress.get("completed_main_question_ids"),
            stage_id,
        )
        supplement_answered = int(progress.get("supplement_answered", 0))
        if active_question_id == SUPPLEMENT_QUESTION_ID:
            supplement_answered = 1
        elif active_question_id is not None and active_question_id not in completed_ids:
            completed_ids.append(active_question_id)
        return InterviewStageRuntime.sync_main_question_progress(
            {
                **progress,
                "completed_main_question_ids": completed_ids,
                "active_main_question_id": None,
                "supplement_answered": supplement_answered,
            }
        )

    @staticmethod
    def set_active_main_question(
        progress: dict[str, Any],
        route_name: str,
        main_question_id: Any,
    ) -> dict[str, Any]:
        if route_name != "normal_interview":
            return {**progress, "active_main_question_id": None}
        stage_id = InterviewStageRuntime.stage_id(progress)
        question_id = InterviewStageRuntime.valid_main_question_id(main_question_id, stage_id)
        if question_id == SUPPLEMENT_QUESTION_ID and int(progress.get("awaiting_stage_completion", 0)):
            return {**progress, "active_main_question_id": question_id}
        if question_id == SUPPLEMENT_QUESTION_ID:
            question_id = None
        return {**progress, "active_main_question_id": question_id}

    @staticmethod
    def answering_supplement(progress: dict[str, Any]) -> bool:
        stage_id = InterviewStageRuntime.stage_id(progress)
        return (
            InterviewStageRuntime.valid_main_question_id(progress.get("active_main_question_id"), stage_id)
            == SUPPLEMENT_QUESTION_ID
        )

    @staticmethod
    def should_finalize_stage(progress: dict[str, Any]) -> bool:
        return bool(progress.get("awaiting_stage_completion") and progress.get("supplement_answered"))

    @staticmethod
    def stage_task(stage_id: str, remaining_rounds: int) -> str:
        if remaining_rounds == 0:
            return (
                "本轮采访任务：当前阶段主问题已经全部收集完成。"
                "暂不切换阶段，继续调用当前阶段主问题提示词，让模型输出编号 9 的补充询问，"
                "询问用户关于当前阶段还有没有没问到但想补充的内容。"
            )
        if stage_id == LAST_INTERVIEW_STAGE and remaining_rounds <= 1:
            return FINAL_STAGE_TASK
        if remaining_rounds > 4:
            return (
                "本轮采访任务：由当前阶段主问题提示词在未收集的主问题中选择一个编号提问，"
                "并在 JSON 中输出本轮提问的问题编号。"
            )
        normalized_remaining = min(max(remaining_rounds, 1), 4)
        return STAGE_TASK_BY_REMAINING_ROUNDS[normalized_remaining]

    @staticmethod
    def transition_hint(progress: dict[str, Any]) -> str:
        existing_hint = str(progress.get("stage_transition_hint") or "").strip()
        if existing_hint:
            return existing_hint[:160]
        stage_id = InterviewStageRuntime.stage_id(progress)
        stage_name = InterviewStageRuntime.stage_name(stage_id) or stage_id
        return f"当前处于{stage_name}阶段，代码状态机未触发阶段跳转；请承接用户回答并保持在当前阶段。"

    @staticmethod
    def cross_stage_instruction(progress: dict[str, Any]) -> str:
        current = progress.get("cross_stage_current")
        if not isinstance(current, dict):
            return ""
        stage_id = str(current.get("stage_id") or "")
        source_stage_id = str(current.get("source_stage_id") or "")
        mention = str(current.get("mention") or "").strip()
        if stage_id not in INTERVIEW_STAGE_BY_ID or source_stage_id not in INTERVIEW_STAGE_BY_ID or not mention:
            return ""
        target_name = InterviewStageRuntime.stage_name(stage_id) or stage_id
        source_name = InterviewStageRuntime.stage_name(source_stage_id) or source_stage_id
        return (
            f"跨阶段挂起线索：用户本轮在{source_name}阶段提到了{target_name}阶段内容：{mention}。"
            f"本轮禁止展开追问该跨阶段内容；只能先自然承接并说明已记下，随后回到{source_name}阶段未覆盖主线问题。"
        )

    @staticmethod
    def stage_description(progress: dict[str, Any]) -> str:
        stage_id = InterviewStageRuntime.stage_id(progress)
        stage = INTERVIEW_STAGE_BY_ID.get(stage_id, INTERVIEW_STAGE_BY_ID[FIRST_INTERVIEW_STAGE])
        valid_ids = InterviewStageRuntime.main_question_ids_for_stage(stage_id)
        completed_ids = InterviewStageRuntime.valid_main_question_ids(
            progress.get("completed_main_question_ids"),
            stage_id,
        )
        pending_ids = [question_id for question_id in valid_ids if question_id not in completed_ids]
        remaining_rounds = len(pending_ids)
        transition_hint = InterviewStageRuntime.transition_hint(progress)
        return "\n".join(
            [
                f"阶段：{stage['id']} {stage['name']}",
                f"必须覆盖：{stage['coverage']}",
                f"边界：{stage['boundary']}",
                f"追问策略：{stage['followup']}",
                f"流程衔接说明：{transition_hint}",
                f"阶段切换衔接：{transition_hint}",
                f"当前阶段建议剩余轮数：{remaining_rounds}",
                f"当前阶段已收集主问题编号：{InterviewStageRuntime.format_main_question_ids(completed_ids)}",
                f"当前阶段待收集主问题编号：{InterviewStageRuntime.format_main_question_ids(pending_ids)}",
                f"当前阶段剩余主问题数量：{remaining_rounds}",
                InterviewStageRuntime.cross_stage_instruction(progress),
                InterviewStageRuntime.stage_task(stage_id, remaining_rounds),
            ]
        )

    @staticmethod
    def next_stage_id(stage_id: str) -> str | None:
        try:
            index = INTERVIEW_STAGE_IDS.index(stage_id)
        except ValueError:
            return FIRST_INTERVIEW_STAGE
        next_index = index + 1
        return INTERVIEW_STAGE_IDS[next_index] if next_index < len(INTERVIEW_STAGE_IDS) else None
