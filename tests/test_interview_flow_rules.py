import asyncio
import json
import unittest
from datetime import UTC, datetime

from app.schemas.interview import InterviewContext
from app.services.interview_agent_service import (
    MAX_HISTORY_MESSAGE_CHARS,
    MAX_HISTORY_MESSAGES,
    InterviewAgentService,
)
from app.services.interview_state_machine import InterviewStateMachine


class MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class InterviewFlowRulesTest(unittest.TestCase):
    def test_format_history_keeps_recent_four_rounds_and_truncates_content(self) -> None:
        messages = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"message-{index}-" + "x" * 800}
            for index in range(12)
        ]

        formatted = InterviewAgentService._format_history(messages)

        self.assertEqual(len(formatted.splitlines()), MAX_HISTORY_MESSAGES)
        self.assertNotIn("message-3", formatted)
        self.assertIn("message-4", formatted)
        self.assertIn("message-11", formatted)
        self.assertNotIn("x" * (MAX_HISTORY_MESSAGE_CHARS + 1), formatted)

    def test_parse_route_forces_emotional_guidance_to_not_decrement(self) -> None:
        raw = json.dumps(
            {
                "route": "emotional_guidance",
                "emotion_type": "anxiety_heavy",
                "confidence": 0.9,
                "reason": "用户表达明显情绪负担。",
                "should_change_topic": True,
                "do_not_probe_current_topic": True,
                "round_decrement": 1,
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw, "压力太大了，想起来就难受", 2)

        self.assertEqual(route.route, "emotional_guidance")
        self.assertEqual(route.round_decrement, 1)

    def test_parse_route_forces_low_engagement_to_decrement(self) -> None:
        raw = json.dumps(
            {
                "route": "emotional_guidance",
                "emotion_type": "unclear",
                "confidence": 0.8,
                "reason": "用户回复很短。",
                "should_change_topic": True,
                "do_not_probe_current_topic": False,
                "round_decrement": 0,
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw, "嗯", 2)

        self.assertEqual(route.route, "emotional_guidance")
        self.assertEqual(route.round_decrement, 1)

    def test_fallback_rich_content_can_follow_up_without_decrement(self) -> None:
        route = InterviewAgentService._fallback_route(
            "我还记得那时候每天很早起来去上学，后来有一次老师当着全班表扬我，这件事让我一直很难忘。",
            2,
        )

        self.assertEqual(route.route, "extended_interview")
        self.assertEqual(route.round_decrement, 0)

    def test_parse_route_keeps_explicit_extended_interview_without_decrement(self) -> None:
        raw = json.dumps(
            {
                "route": "extended_interview",
                "emotion_type": "none",
                "confidence": 0.86,
                "reason": "用户表达稳定，内容具体。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
                "round_decrement": 1,
            },
            ensure_ascii=False,
        )
        user_message = "那时候我还记得特别清楚，当时一个人去外地工作，后来第一次拿到工资，心里又紧张又高兴，这件事到现在印象很深。"

        route = InterviewAgentService._parse_route(raw, user_message, 2)

        self.assertEqual(route.route, "extended_interview")
        self.assertEqual(route.round_decrement, 0)

    def test_stage_entry_can_extend_when_expandable_material_appears(self) -> None:
        raw = json.dumps(
            {
                "route": "extended_interview",
                "emotion_type": "none",
                "confidence": 0.86,
                "reason": "用户提到小时候钓鱼，有可扩展素材。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
                "round_decrement": 0,
                "detected_stage": "S1",
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw, "这个跟我小时候一样，平时喜欢钓鱼。", 4)

        self.assertEqual(route.route, "extended_interview")
        self.assertEqual(route.round_decrement, 0)

    def test_fallback_stage_entry_extends_with_rich_content(self) -> None:
        route = InterviewAgentService._fallback_route(
            "这个跟我小时候一样，平时喜欢钓鱼，后来经常和同学一起去河边，一待就是半天。",
            4,
        )

        self.assertEqual(route.route, "extended_interview")
        self.assertEqual(route.round_decrement, 0)

    def test_first_answer_memorable_event_can_extend(self) -> None:
        route = InterviewAgentService._fallback_route("印象最深的是第一次离家去深圳打工", 4)

        self.assertEqual(route.route, "extended_interview")
        self.assertEqual(route.round_decrement, 0)

    def test_relationship_support_short_answer_can_extend(self) -> None:
        route = InterviewAgentService._fallback_route("有我的女朋友给了我很多鼓励", 0)

        self.assertEqual(route.route, "extended_interview")
        self.assertEqual(route.round_decrement, 0)

    def test_parse_route_treats_collective_memory_as_followup_candidate(self) -> None:
        raw = json.dumps(
            {
                "route": "extended_interview",
                "emotion_type": "none",
                "confidence": 0.82,
                "reason": "用户在讲童年环境。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
                "round_decrement": 1,
            },
            ensure_ascii=False,
        )
        user_message = "我们那个院子里大家都很熟，谁家做了饭会端出来分一点，周围的人有事也互相招呼，这种关系一直没变。"

        route = InterviewAgentService._parse_route(raw, user_message, 3)

        self.assertEqual(route.route, "extended_interview")
        self.assertEqual(route.round_decrement, 0)

    def test_parse_route_keeps_plain_normal_turn_decrementing(self) -> None:
        raw = json.dumps(
            {
                "route": "normal_interview",
                "emotion_type": "none",
                "confidence": 0.7,
                "reason": "用户表达稳定。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
                "round_decrement": 1,
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw, "那时候主要是在家里帮忙。", 2)

        self.assertEqual(route.route, "normal_interview")
        self.assertEqual(route.round_decrement, 1)

    def test_parse_route_corrects_llm_childhood_misclassification_for_work(self) -> None:
        raw = json.dumps(
            {
                "route": "extended_interview",
                "emotion_type": "none",
                "confidence": 0.8,
                "reason": "用户内容具体。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
                "round_decrement": 0,
                "detected_stage": "S1",
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw, "我在深圳打工那几年，刚开始什么都不熟。", 2)

        self.assertEqual(route.detected_stage, "S2")

    def test_plain_response_after_extension_returns_to_main_flow(self) -> None:
        raw = json.dumps(
            {
                "route": "normal_interview",
                "emotion_type": "none",
                "confidence": 0.7,
                "reason": "扩展追问后用户反响一般，没有新增素材。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
                "round_decrement": 1,
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw, "也差不多就是这样。", 2)

        self.assertEqual(route.route, "normal_interview")
        self.assertEqual(route.round_decrement, 1)

    def test_normal_route_with_decrement_uses_planned_flow_prompt(self) -> None:
        service = InterviewAgentService()
        route = InterviewAgentService._parse_route(
            json.dumps(
                {
                    "route": "normal_interview",
                    "emotion_type": "none",
                    "confidence": 0.7,
                    "reason": "用户表达稳定。",
                    "should_change_topic": False,
                    "do_not_probe_current_topic": False,
                    "round_decrement": 1,
                },
                ensure_ascii=False,
            ),
            "那时候主要是在家里帮忙。",
            2,
        )

        prompt = service._build_reply_prompt(
            route,
            "那时候主要是在家里帮忙。",
            [],
            "阶段：S1 童年时光\n本轮采访任务：环境与处境",
            2,
        )

        self.assertIn("当前还处于计划流程推进阶段", prompt)
        self.assertIn("按“本轮采访任务”补齐主流程信息", prompt)
        self.assertNotIn("本轮不推进计划流程", prompt)

    def test_extended_route_uses_detail_followup_prompt(self) -> None:
        service = InterviewAgentService()
        route = InterviewAgentService._parse_route(
            json.dumps(
                {
                    "route": "extended_interview",
                    "emotion_type": "none",
                    "confidence": 0.86,
                    "reason": "用户表达稳定，内容具体。",
                    "should_change_topic": False,
                    "do_not_probe_current_topic": False,
                    "round_decrement": 1,
                },
                ensure_ascii=False,
            ),
            "那时候我还记得特别清楚，当时一个人去外地工作，后来第一次拿到工资，心里又紧张又高兴，这件事到现在印象很深。",
            2,
        )

        prompt = service._build_reply_prompt(
            route,
            "那时候我还记得特别清楚，当时一个人去外地工作，后来第一次拿到工资，心里又紧张又高兴，这件事到现在印象很深。",
            [],
            "阶段：S2 青春岁月\n本轮采访任务：日常主线与关键事件",
            2,
        )

        self.assertEqual(route.round_decrement, 0)
        self.assertIn("生成采访者下一句扩展追问", prompt)
        self.assertIn("本轮不推进计划流程", prompt)
        self.assertNotIn("当前还处于计划流程推进阶段", prompt)

    def test_stage_task_clamps_legacy_remaining_rounds(self) -> None:
        task = InterviewStateMachine._stage_task("S1", 4)

        self.assertIn("环境与处境", task)

    def test_stage_description_is_compact_structured_context(self) -> None:
        description = InterviewStateMachine._stage_description(
            {"stage_id": "S1", "remaining_rounds": 4, "completed": 0}
        )

        self.assertIn("阶段：S1 童年时光", description)
        self.assertIn("必须覆盖：", description)
        self.assertIn("阶段切换衔接：无", description)
        self.assertIn("本轮采访任务：环境与处境", description)
        self.assertLess(len(description), 500)

    def test_initial_detected_stage_can_start_from_user_mentioned_stage(self) -> None:
        progress = {"stage_id": "S1", "remaining_rounds": 4, "completed": 0}
        updated = InterviewStateMachine._apply_initial_detected_stage(
            progress,
            "我最想先说结婚成家那几年，孩子出生以后责任一下子重了。",
            [],
        )

        self.assertEqual(updated["stage_id"], "S3")
        self.assertEqual(updated["remaining_rounds"], 4)

    def test_stage_detection_treats_shenzhen_work_as_youth_not_childhood(self) -> None:
        stage = InterviewAgentService._detect_stage("我在深圳打工那几年，刚开始什么都不熟。")

        self.assertEqual(stage, "S2")

    def test_stage_detection_requires_childhood_context_for_s1(self) -> None:
        stage = InterviewAgentService._detect_stage("我12岁以前一直在老家，小时候主要帮父母干活。")

        self.assertEqual(stage, "S1")

    def test_stage_detection_treats_married_work_for_family_as_turning_point(self) -> None:
        stage = InterviewAgentService._detect_stage("结婚后我去深圳打工养家，孩子还小，那几年压力特别大。")

        self.assertEqual(stage, "S3")

    def test_low_engagement_returns_to_current_stage_main_question(self) -> None:
        progress = {"stage_id": "S2", "remaining_rounds": 2, "completed": 0}
        route = InterviewAgentService._fallback_route("记不清了", 2)

        updated = InterviewStateMachine._apply_route_stage_shift(progress, route)

        self.assertEqual(updated["stage_id"], "S2")
        self.assertEqual(updated["remaining_rounds"], 2)
        self.assertEqual(route.round_decrement, 1)

    def test_resistance_after_extension_returns_to_current_stage_main_question(self) -> None:
        progress = {"stage_id": "S2", "remaining_rounds": 3, "completed": 0}
        route = InterviewAgentService._fallback_route("这个不想说了，跳过吧", 3)

        updated = InterviewStateMachine._apply_route_stage_shift(progress, route)
        reply = InterviewAgentService._fallback_reply(
            route,
            "阶段：S2 青春岁月\n本轮采访任务：日常主线。下一问要覆盖这段时期平日主要怎么过、主要在忙什么。",
            "这个不想说了，跳过吧",
        )

        self.assertEqual(updated["stage_id"], "S2")
        self.assertEqual(updated["remaining_rounds"], 3)
        self.assertEqual(route.round_decrement, 1)
        self.assertIn("不顺着这里深聊", reply)
        self.assertIn("平日里主要是怎么过", reply)

    def test_negative_emotion_stays_in_current_stage_and_advances_main_question(self) -> None:
        progress = {"stage_id": "S2", "remaining_rounds": 3, "completed": 0}
        route = InterviewAgentService._fallback_route("那时候确实不容易，现在想起来挺感慨。", 3)

        updated = InterviewStateMachine._apply_route_stage_shift(progress, route)

        self.assertEqual(route.route, "emotional_guidance")
        self.assertEqual(route.round_decrement, 1)
        self.assertEqual(updated["stage_id"], "S2")

    def test_emotional_fallback_reply_returns_to_current_main_question(self) -> None:
        route = InterviewAgentService._fallback_route("那时候压力太大，想起来就难受。", 3)
        reply = InterviewAgentService._fallback_reply(
            route,
            "阶段：S3 人生转折\n本轮采访任务：关键事件。下一问要覆盖这段时期最有代表性的一件大事、转折、高光或困难。",
            "那时候压力太大，想起来就难受。",
        )

        self.assertIn("不深挖难受的地方", reply)
        self.assertIn("比较有代表性的事", reply)

    def test_final_stage_fallback_reply_ends_without_new_question(self) -> None:
        route = InterviewAgentService._fallback_route("谢谢，我也说得差不多了。", 1)
        reply = InterviewAgentService._fallback_reply(route, "阶段：S5 收尾总结\n本轮采访任务：最终收尾")

        self.assertIn("今天的采访就先到这里", reply)
        self.assertNotIn("？", reply)

    def test_interview_progress_does_not_advance_when_round_decrement_is_zero(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {"stage_id": "S1", "remaining_rounds": 3, "completed": 0}

            updated = await service._advance_interview_progress(context, progress, round_decrement=0)

            self.assertEqual(updated["stage_id"], "S1")
            self.assertEqual(updated["remaining_rounds"], 3)
            self.assertEqual(updated["completed"], 0)

        asyncio.run(run_case())

    def test_interview_progress_waits_for_answer_before_stage_switch(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {"stage_id": "S1", "remaining_rounds": 1, "completed": 0}

            updated = await service._advance_interview_progress(context, progress, round_decrement=1)

            self.assertEqual(updated["stage_id"], "S1")
            self.assertEqual(updated["remaining_rounds"], 0)
            self.assertEqual(updated["completed"], 0)
            self.assertEqual(updated["awaiting_stage_completion"], 1)

        asyncio.run(run_case())

    def test_awaiting_stage_completion_switches_after_user_answer(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S1",
                "remaining_rounds": 0,
                "completed": 0,
                "visited_stage_ids": [],
                "pending_stage_ids": [],
                "awaiting_stage_completion": 1,
            }

            updated = await service._complete_awaiting_stage_if_needed(context, progress)

            self.assertEqual(updated["stage_id"], "S2")
            self.assertEqual(updated["remaining_rounds"], 4)
            self.assertEqual(updated["completed"], 0)
            self.assertEqual(updated["awaiting_stage_completion"], 0)
            self.assertEqual(updated["visited_stage_ids"], ["S1"])

        asyncio.run(run_case())

    def test_awaiting_stage_completion_extends_relationship_support_before_switching(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S3",
                "remaining_rounds": 0,
                "completed": 0,
                "visited_stage_ids": [],
                "pending_stage_ids": [],
                "awaiting_stage_completion": 1,
            }
            route = InterviewAgentService._fallback_route("有我的女朋友给了我很多鼓励", 0)

            if int(progress.get("awaiting_stage_completion", 0)) and route.route != "extended_interview":
                progress = await service._complete_awaiting_stage_if_needed(context, progress)
            updated = await service._advance_interview_progress(context, progress, round_decrement=route.round_decrement)

            self.assertEqual(route.route, "extended_interview")
            self.assertEqual(updated["stage_id"], "S3")
            self.assertEqual(updated["awaiting_stage_completion"], 1)
            self.assertEqual(updated["remaining_rounds"], 0)

        asyncio.run(run_case())

    def test_interview_progress_backfills_unvisited_stages_after_user_chosen_start(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S3",
                "remaining_rounds": 1,
                "completed": 0,
                "visited_stage_ids": [],
                "pending_stage_ids": [],
            }

            waiting = await service._advance_interview_progress(context, progress, round_decrement=1)
            updated = await service._complete_awaiting_stage_if_needed(context, waiting)

            self.assertEqual(updated["stage_id"], "S1")
            self.assertEqual(updated["remaining_rounds"], 4)
            self.assertEqual(updated["visited_stage_ids"], ["S3"])

        asyncio.run(run_case())

    def test_detected_stage_mention_is_prioritized_after_current_stage_finishes(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S3",
                "remaining_rounds": 1,
                "completed": 0,
                "visited_stage_ids": [],
                "pending_stage_ids": ["S4"],
            }

            waiting = await service._advance_interview_progress(context, progress, round_decrement=1)
            updated = await service._complete_awaiting_stage_if_needed(context, waiting)

            self.assertEqual(updated["stage_id"], "S4")
            self.assertEqual(updated["remaining_rounds"], 4)
            self.assertEqual(updated["visited_stage_ids"], ["S3"])

        asyncio.run(run_case())

    def test_pending_stage_transition_carries_user_mentioned_context(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S3",
                "remaining_rounds": 1,
                "completed": 0,
                "visited_stage_ids": [],
                "pending_stage_ids": ["S4"],
                "pending_stage_mentions": {"S4": "现在退休后倒是轻松多了"},
            }

            waiting = await service._advance_interview_progress(context, progress, round_decrement=1)
            updated = await service._complete_awaiting_stage_if_needed(context, waiting)
            description = InterviewStateMachine._stage_description(updated)

            self.assertEqual(updated["stage_id"], "S4")
            self.assertIn("现在退休后倒是轻松多了", description)
            self.assertIn("阶段切换衔接：用户上一阶段曾提到", description)

        asyncio.run(run_case())

    def test_completed_stages_are_skipped_when_backfilling(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S1",
                "remaining_rounds": 1,
                "completed": 0,
                "visited_stage_ids": ["S3"],
                "pending_stage_ids": [],
            }

            waiting = await service._advance_interview_progress(context, progress, round_decrement=1)
            updated = await service._complete_awaiting_stage_if_needed(context, waiting)

            self.assertEqual(updated["stage_id"], "S2")
            self.assertEqual(updated["visited_stage_ids"], ["S3", "S1"])
            description = InterviewStateMachine._stage_description(updated)
            self.assertIn("阶段切换衔接：无", description)

        asyncio.run(run_case())

    def test_final_stage_ends_only_after_user_answers_last_question(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S5",
                "remaining_rounds": 1,
                "completed": 0,
                "visited_stage_ids": ["S1", "S2", "S3", "S4"],
                "pending_stage_ids": [],
            }

            waiting = await service._advance_interview_progress(context, progress, round_decrement=1)
            self.assertEqual(waiting["stage_id"], "S5")
            self.assertEqual(waiting["completed"], 0)
            self.assertEqual(waiting["awaiting_stage_completion"], 1)

            updated = await service._complete_awaiting_stage_if_needed(context, waiting)
            self.assertEqual(updated["completed"], 1)
            self.assertEqual(updated["awaiting_stage_completion"], 0)
            self.assertEqual(updated["visited_stage_ids"], ["S1", "S2", "S3", "S4", "S5"])

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
