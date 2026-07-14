import asyncio
import json
import unittest
from datetime import UTC, datetime

from app.schemas.interview import InterviewContext
from app.graphs.interview_stage_subgraph import InterviewStageSubgraph, stage_route_counts_as_answer
from app.services.interview_agent_service import (
    MAX_HISTORY_MESSAGE_CHARS,
    MAX_HISTORY_MESSAGES,
    InterviewAgentService,
    InterviewReplyResult,
    InterviewRouteResult,
    InterviewStageDetectionResult,
    InterviewStageRouteResult,
)
from app.services.interview_state_machine import InterviewStateMachine
from app.services.langgraph_redis_checkpoint import RedisCheckpointSaver


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
        if end == -1:
            end = len(values) - 1
        return values[start : end + 1]


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

    def test_format_history_can_include_full_stage_history(self) -> None:
        messages = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"message-{index}"}
            for index in range(12)
        ]

        formatted = InterviewAgentService._format_history(messages, limit=None)

        self.assertEqual(len(formatted.splitlines()), 12)
        self.assertIn("message-0", formatted)
        self.assertIn("message-11", formatted)

    def test_normalize_reply_removes_interviewer_prefix(self) -> None:
        reply = InterviewAgentService._normalize_reply("采：那时候最让您难忘的是什么？")

        self.assertEqual(reply, "那时候最让您难忘的是什么？")

    def test_langgraph_selects_reply_node_from_route(self) -> None:
        self.assertEqual(
            InterviewAgentService._select_reply_node({"route": InterviewRouteResult(route="normal_interview")}),
            "normal_reply",
        )
        self.assertEqual(
            InterviewAgentService._select_reply_node({"route": InterviewRouteResult(route="extended_interview")}),
            "extended_reply",
        )
        self.assertEqual(
            InterviewAgentService._select_reply_node({"route": InterviewRouteResult(route="emotional_guidance")}),
            "normal_reply",
        )

    def test_stage_subgraph_low_information_does_not_count_active_question(self) -> None:
        async def run_case() -> None:
            service = InterviewAgentService()

            async def fake_judge_stage_route(**_: object) -> InterviewStageRouteResult:
                return InterviewStageRouteResult(route="low_information", confidence=0.9)

            async def fake_low_information_reply(**_: object) -> str:
                return "That is okay. We can start with one small detail."

            async def fail_generate_reply_for_route(**_: object) -> tuple[str, str, int | None]:
                raise AssertionError("low information should not enter normal reply generation")

            service.judge_stage_route = fake_judge_stage_route  # type: ignore[method-assign]
            service.generate_low_information_reply = fake_low_information_reply  # type: ignore[method-assign]
            service.generate_reply_for_route = fail_generate_reply_for_route  # type: ignore[method-assign]

            graph = InterviewStageSubgraph(service)
            state = await graph.run(
                {
                    "session_id": "session-stage-low",
                    "stage_id": "S1",
                    "local_messages": [],
                    "user_message": "continue",
                    "stage_description": "stage S1",
                    "remaining_rounds": 5,
                    "completed_main_question_ids": [],
                    "active_main_question_id": 1,
                }
            )

            self.assertFalse(stage_route_counts_as_answer(state["stage_route"]["route"]))
            self.assertFalse(state["answer_counted"])
            self.assertEqual(state["main_question_id"], None)
            self.assertIn("small detail", state["assistant_message"])

        asyncio.run(run_case())

    def test_stage_subgraph_normal_answer_counts_active_question_for_next_prompt(self) -> None:
        async def run_case() -> None:
            service = InterviewAgentService()
            captured_completed_ids: list[int] = []

            async def fake_judge_stage_route(**_: object) -> InterviewStageRouteResult:
                return InterviewStageRouteResult(route="normal_answer", confidence=0.9)

            async def fake_generate_reply_for_route(**kwargs: object) -> tuple[str, str, int | None]:
                captured_completed_ids.extend(kwargs["completed_main_question_ids"])  # type: ignore[arg-type]
                return "Next question", "llm", 2

            service.judge_stage_route = fake_judge_stage_route  # type: ignore[method-assign]
            service.generate_reply_for_route = fake_generate_reply_for_route  # type: ignore[method-assign]

            graph = InterviewStageSubgraph(service)
            state = await graph.run(
                {
                    "session_id": "session-stage-normal",
                    "stage_id": "S1",
                    "local_messages": [],
                    "user_message": "I lived with my grandparents by the river.",
                    "stage_description": "stage S1",
                    "remaining_rounds": 5,
                    "completed_main_question_ids": [],
                    "active_main_question_id": 1,
                }
            )

            self.assertTrue(stage_route_counts_as_answer(state["stage_route"]["route"]))
            self.assertTrue(state["answer_counted"])
            self.assertEqual(captured_completed_ids, [1])
            self.assertEqual(state["main_question_id"], 2)

        asyncio.run(run_case())

    def test_langgraph_checkpoint_persists_turn_state(self) -> None:
        async def run_case() -> None:
            service = InterviewAgentService(checkpointer=RedisCheckpointSaver(MemoryRedis()))  # type: ignore[arg-type]

            async def fake_generate_reply(**_: object) -> InterviewReplyResult:
                return InterviewReplyResult(reply="那段日子里，最主要的生活处境是什么样的？", main_question_id=1)

            service._generate_reply = fake_generate_reply  # type: ignore[method-assign]

            reply, response_source, main_question_id = await service.generate_reply_for_route(
                route=InterviewRouteResult(route="normal_interview"),
                session_id="session-graph",
                interview_progress={"stage_id": "S2", "completed": 0},
                user_message="那时候刚离开老家。",
                recent_messages=[],
                stage_description="阶段：S2 青春岁月",
                remaining_rounds=8,
                completed_main_question_ids=[],
            )
            snapshot = await service._turn_graph.aget_state(service._graph_config("session-graph"))

            self.assertEqual(reply, "那段日子里，最主要的生活处境是什么样的？")
            self.assertEqual(response_source, "llm")
            self.assertEqual(main_question_id, 1)
            self.assertEqual(snapshot.values["interview_progress"]["stage_id"], "S2")
            self.assertEqual(snapshot.values["reply"], reply)

        asyncio.run(run_case())

    def test_parse_route_normalizes_emotional_guidance_to_normal(self) -> None:
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

        route = InterviewAgentService._parse_route(raw)

        self.assertEqual(route.route, "normal_interview")
        self.assertEqual(route.emotion_type, "anxiety_heavy")
        self.assertTrue(route.needs_emotional_support)
        self.assertTrue(route.should_change_topic)
        self.assertTrue(route.do_not_probe_current_topic)
        self.assertEqual(route.round_decrement, 1)

    def test_parse_route_derives_decrement_when_model_omits_it(self) -> None:
        raw = json.dumps(
            {
                "route": "normal_interview",
                "emotion_type": "none",
                "confidence": 0.8,
                "reason": "用户回答稳定，应回到主流程。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw)

        self.assertEqual(route.route, "normal_interview")
        self.assertFalse(route.needs_emotional_support)
        self.assertEqual(route.round_decrement, 1)

    def test_parse_route_keeps_explicit_emotional_support_flag(self) -> None:
        raw = json.dumps(
            {
                "route": "extended_interview",
                "emotion_type": "sadness",
                "needs_emotional_support": True,
                "confidence": 0.82,
                "reason": "用户讲到难过但仍提供了具体事件。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw)

        self.assertEqual(route.route, "extended_interview")
        self.assertTrue(route.needs_emotional_support)
        self.assertEqual(route.round_decrement, 0)

    def test_parse_route_derives_emotional_support_from_emotion_type(self) -> None:
        raw = json.dumps(
            {
                "route": "normal_interview",
                "emotion_type": "regret_self_blame",
                "confidence": 0.78,
                "reason": "用户表达明显遗憾和自责。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw)

        self.assertEqual(route.route, "normal_interview")
        self.assertTrue(route.needs_emotional_support)
        self.assertEqual(route.round_decrement, 1)

    def test_parse_route_ignores_legacy_emotional_guidance_decrement(self) -> None:
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

        route = InterviewAgentService._parse_route(raw)

        self.assertEqual(route.route, "normal_interview")
        self.assertEqual(route.round_decrement, 1)

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

        route = InterviewAgentService._parse_route(raw)

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
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw)

        self.assertEqual(route.route, "extended_interview")
        self.assertEqual(route.round_decrement, 0)

    def test_parse_route_keeps_model_normal_for_relationship_support(self) -> None:
        raw = json.dumps(
            {
                "route": "normal_interview",
                "emotion_type": "none",
                "confidence": 0.72,
                "reason": "用户回答稳定。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
                "round_decrement": 1,
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw)

        self.assertEqual(route.route, "normal_interview")
        self.assertEqual(route.round_decrement, 1)

    def test_parse_route_keeps_model_normal_for_memorable_first_event(self) -> None:
        raw = json.dumps(
            {
                "route": "normal_interview",
                "emotion_type": "none",
                "confidence": 0.72,
                "reason": "用户回答稳定。",
                "should_change_topic": False,
                "do_not_probe_current_topic": False,
                "round_decrement": 1,
            },
            ensure_ascii=False,
        )

        route = InterviewAgentService._parse_route(raw)

        self.assertEqual(route.route, "normal_interview")
        self.assertEqual(route.round_decrement, 1)

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

        route = InterviewAgentService._parse_route(raw)

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

        route = InterviewAgentService._parse_route(raw)

        self.assertEqual(route.route, "normal_interview")
        self.assertEqual(route.round_decrement, 1)

    def test_parse_stage_detection_normalizes_stage_name(self) -> None:
        raw = json.dumps(
            {
                "stage_code": "S4",
                "stage_name": "模型写错也以代码为准",
                "judgment_reason": "讲述退休后的生活。",
            },
            ensure_ascii=False,
        )

        result = InterviewAgentService._parse_stage_detection(raw)

        self.assertEqual(result.stage_code, "S4")
        self.assertEqual(result.stage_name, "岁月阅历")
        self.assertEqual(result.judgment_reason, "讲述退休后的生活。")

    def test_parse_stage_detection_treats_invalid_stage_as_unclear(self) -> None:
        raw = json.dumps(
            {
                "stage_code": "S9",
                "stage_name": "未知",
                "judgment_reason": "无法确认。",
            },
            ensure_ascii=False,
        )

        result = InterviewAgentService._parse_stage_detection(raw)

        self.assertEqual(result.stage_code, "unclear")
        self.assertEqual(result.stage_name, "未识别")

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

        route = InterviewAgentService._parse_route(raw)

        self.assertEqual(route.route, "normal_interview")
        self.assertEqual(route.round_decrement, 1)

    def test_parse_main_question_reply_extracts_reply_and_question_id(self) -> None:
        raw = json.dumps({"question": "next question", "question_id": "3"})

        result = InterviewAgentService._parse_main_question_reply(raw)

        self.assertEqual(result.reply, "next question")
        self.assertEqual(result.main_question_id, 3)

    def test_parse_main_question_reply_allows_supplement_question_id_when_stage_complete(self) -> None:
        raw = json.dumps({"question": "anything else?", "question_id": "9"})

        result = InterviewAgentService._parse_main_question_reply(raw, allow_supplement=True)

        self.assertEqual(result.reply, "anything else?")
        self.assertEqual(result.main_question_id, 9)

    def test_parse_main_question_reply_rejects_invalid_question_id(self) -> None:
        raw = json.dumps({"reply": "next question", "question_id": 9})

        with self.assertRaises(ValueError):
            InterviewAgentService._parse_main_question_reply(raw)

    def test_set_active_main_question_tracks_supplement_without_counting_it(self) -> None:
        progress = {
            "stage_id": "S1",
            "awaiting_stage_completion": 1,
            "completed_main_question_ids": list(range(1, 9)),
        }

        updated = InterviewStateMachine._set_active_main_question(progress, "normal_interview", 9)

        self.assertEqual(updated["active_main_question_id"], 9)
        answered = InterviewStateMachine._mark_active_main_question_answered(updated)
        self.assertEqual(answered["completed_main_question_ids"], list(range(1, 9)))
        self.assertEqual(answered["supplement_answered"], 1)

    def test_stage_messages_include_only_current_stage_with_legacy_fallback(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            await service._append_message("session-1", "assistant", "开场")
            await service._append_message("session-1", "user", "童年回答", stage_id="S1")
            await service._append_message("session-1", "assistant", "童年问题", stage_id="S1")
            await service._append_message("session-1", "user", "青春回答", stage_id="S2")

            s1_messages = await service._get_stage_messages("session-1", "S1")
            s3_messages = await service._get_stage_messages("session-1", "S3")

            self.assertEqual([message["content"] for message in s1_messages], ["童年回答", "童年问题"])
            self.assertEqual([message["content"] for message in s3_messages], ["开场"])

        asyncio.run(run_case())

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
            )
        )

        prompt = service._build_reply_prompt(
            route,
            "那时候主要是在家里帮忙。",
            [{"role": "assistant", "content": "旧问题"}, {"role": "user", "content": "旧回答"}],
            "阶段：S1 童年时光\n本轮采访任务：环境与处境",
            2,
            [1, 3],
        )

        self.assertIn("个人传记【童年阶段】采访主持人", prompt)
        self.assertIn("【本阶段全部历史对话】", prompt)
        self.assertIn("采：旧问题", prompt)
        self.assertIn("受：旧回答", prompt)
        self.assertIn("【当前阶段已收集主问题编号】\n1、3", prompt)
        self.assertIn("【用户上一轮最新回答】\n那时候主要是在家里帮忙。", prompt)
        self.assertIn("历史承接与情绪覆盖规则", prompt)
        self.assertIn("默认历史承接", prompt)
        self.assertIn("情绪安慰规则只覆盖“如何承接用户上一轮回答”", prompt)
        self.assertNotIn("{{", prompt)
        self.assertNotIn("本轮不推进计划流程", prompt)
        self.assertNotIn("## 情绪安慰融合规则", prompt)

    def test_normal_prompt_appends_emotional_support_rules_when_needed(self) -> None:
        service = InterviewAgentService()
        route = InterviewAgentService._parse_route(
            json.dumps(
                {
                    "route": "normal_interview",
                    "emotion_type": "anxiety_heavy",
                    "needs_emotional_support": True,
                    "confidence": 0.86,
                    "reason": "用户表达压力沉重，需要降压承接。",
                    "should_change_topic": True,
                    "do_not_probe_current_topic": True,
                },
                ensure_ascii=False,
            )
        )

        prompt = service._build_reply_prompt(
            route,
            "那段时间压力很大，不太想细说。",
            [],
            "阶段：S3 人生转折\n本轮采访任务：由当前阶段主问题提示词在 1-8 号主问题中选择",
            6,
            [1, 2],
        )

        self.assertIn("情绪安慰融合规则", prompt)
        self.assertIn("本规则只覆盖当前主问题/追问提示词中的“历史承接、过渡语、共情回应”写法", prompt)
        self.assertIn("本规则不覆盖当前采访任务", prompt)
        self.assertIn("仍然只输出包含 question_id 和 question 的 JSON", prompt)
        self.assertIn("安慰只放进 question 字段里", prompt)
        self.assertIn("当 emotion_type = anxiety_heavy 时使用", prompt)
        self.assertIn("这种压力不是一句话能说轻的", prompt)
        self.assertNotIn("当 emotion_type = sadness 时使用", prompt)
        self.assertIn('"needs_emotional_support":true', prompt)
        self.assertNotIn("route = emotional_guidance", prompt)

    def test_emotional_support_unknown_type_uses_unclear_rules(self) -> None:
        service = InterviewAgentService()
        route = InterviewRouteResult(
            route="normal_interview",
            emotion_type="unexpected",
            needs_emotional_support=True,
        )

        prompt = service._build_reply_prompt(
            route,
            "这段不太好说。",
            [],
            "阶段：S3 人生转折\n本轮采访任务：由当前阶段主问题提示词在 1-8 号主问题中选择",
            6,
            [],
        )

        self.assertIn("当 emotion_type = unclear 或无法匹配具体情绪类型时使用", prompt)
        self.assertIn("不给用户贴情绪标签", prompt)

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
            )
        )

        prompt = service._build_reply_prompt(
            route,
            "那时候我还记得特别清楚，当时一个人去外地工作，后来第一次拿到工资，心里又紧张又高兴，这件事到现在印象很深。",
            [],
            "阶段：S2 青春岁月\n本轮采访任务：日常主线与关键事件",
            2,
        )

        self.assertEqual(route.round_decrement, 0)
        self.assertIn("个人传记青春岁月阶段专属采访者", prompt)
        self.assertIn("无新内容可追问时返回指定指令", prompt)
        self.assertIn("【本阶段全部历史对话】", prompt)
        self.assertIn("【当前阶段已收集主问题编号】\n无", prompt)
        self.assertIn("历史承接与情绪覆盖规则", prompt)
        self.assertIn("情绪安慰规则只覆盖“如何承接用户本轮情绪”", prompt)
        self.assertIn("route", prompt)
        self.assertNotIn("{{", prompt)
        self.assertNotIn("当前还处于计划流程推进阶段", prompt)
        self.assertNotIn("## 情绪安慰融合规则", prompt)

    def test_extended_prompt_appends_emotional_support_rules_when_needed(self) -> None:
        service = InterviewAgentService()
        route = InterviewAgentService._parse_route(
            json.dumps(
                {
                    "route": "extended_interview",
                    "emotion_type": "sadness",
                    "needs_emotional_support": True,
                    "confidence": 0.84,
                    "reason": "用户讲到难过经历且仍有具体素材。",
                    "should_change_topic": False,
                    "do_not_probe_current_topic": False,
                },
                ensure_ascii=False,
            )
        )

        prompt = service._build_reply_prompt(
            route,
            "那次比赛输了以后我挺难受，但师父一直陪着我复盘。",
            [],
            "阶段：S2 青春岁月\n本轮采访任务：由当前阶段主问题提示词在 1-8 号主问题中选择",
            5,
            [1],
        )

        self.assertIn("情绪安慰融合规则", prompt)
        self.assertIn("本规则只覆盖当前主问题/追问提示词中的“历史承接、过渡语、共情回应”写法", prompt)
        self.assertIn("本规则不覆盖当前采访任务", prompt)
        self.assertIn("仍然只输出一句采访话术", prompt)
        self.assertIn("先安慰，再围绕当前素材问一个低压力开放问题", prompt)
        self.assertIn("当 emotion_type = sadness 时使用", prompt)
        self.assertIn("这段记忆里确实有些沉", prompt)
        self.assertNotIn("当 emotion_type = anxiety_heavy 时使用", prompt)
        self.assertIn('"needs_emotional_support":true', prompt)
        self.assertNotIn("route = emotional_guidance", prompt)

    def test_stage_task_clamps_legacy_remaining_rounds(self) -> None:
        task = InterviewStateMachine._stage_task("S1", 4)

        self.assertIn("环境与处境", task)

    def test_stage_description_is_compact_structured_context(self) -> None:
        description = InterviewStateMachine._stage_description(
            {"stage_id": "S1", "remaining_rounds": 4, "completed": 0}
        )

        self.assertIn("阶段：S1 童年时光", description)
        self.assertIn("必须覆盖：", description)
        self.assertIn("流程衔接说明：当前处于童年时光阶段", description)
        self.assertIn("阶段切换衔接：当前处于童年时光阶段", description)
        self.assertNotIn("阶段切换衔接：无", description)
        self.assertIn("当前阶段已收集主问题编号：无", description)
        self.assertIn("当前阶段待收集主问题编号：1、2、3、4、5、6、7、8", description)
        self.assertIn("当前阶段剩余主问题数量：8", description)
        self.assertIn("本轮采访任务：由当前阶段主问题提示词在 1-8 号主问题中选择", description)
        self.assertLess(len(description), 780)

    def test_initial_detected_stage_can_start_from_user_mentioned_stage(self) -> None:
        progress = {"stage_id": "S1", "remaining_rounds": 4, "completed": 0}
        detection = InterviewStageDetectionResult(stage_code="S3")
        updated = InterviewStateMachine._apply_initial_detected_stage(
            progress,
            detection,
            [],
        )

        self.assertEqual(updated["stage_id"], "S3")
        self.assertNotIn("remaining_rounds", updated)
        self.assertEqual(InterviewStateMachine._remaining_main_question_count(updated), 8)
        self.assertEqual(updated["started_stage_id"], "S3")
        self.assertEqual(updated["stage_flow"][0]["stage_id"], "S3")
        self.assertEqual(updated["stage_flow"][0]["status"], "active")

    def test_initial_unclear_stage_records_default_start_stage(self) -> None:
        progress = {"stage_id": "S1", "remaining_rounds": 8, "completed": 0}
        detection = InterviewStageDetectionResult(stage_code="unclear")

        updated = InterviewStateMachine._apply_initial_detected_stage(progress, detection, [])

        self.assertEqual(updated["started_stage_id"], "S1")
        self.assertEqual(updated["stage_flow"][0]["stage_id"], "S1")
        self.assertEqual(updated["stage_flow"][0]["status"], "active")
        self.assertNotIn("stage_statuses", updated)

    def test_progress_view_records_compact_stage_snapshot(self) -> None:
        progress = InterviewStateMachine._sync_stage_flow(
            {
                "stage_id": "S3",
                "remaining_rounds": 6,
                "completed": 0,
                "completed_main_question_ids": [1, 4],
                "visited_stage_ids": ["S1"],
                "pending_stage_ids": ["S4"],
                "pending_stage_mentions": {"S4": "退休后清闲一些"},
                "stage_statuses": {"S1": "completed", "S2": "not_started", "S3": "active", "S4": "pending"},
                "stage_flow": [
                    {"stage_id": "S1", "stage_name": "童年时光", "status": "completed"},
                    {"stage_id": "S3", "stage_name": "人生转折", "status": "active"},
                ],
                "started_stage_id": "S3",
            }
        )
        view = InterviewStateMachine._hydrate_progress_view(progress)

        self.assertEqual(view["stage_id"], "S3")
        self.assertNotIn("stage_name", view)
        self.assertNotIn("stage_order", view)
        self.assertNotIn("remaining_rounds", view)
        self.assertNotIn("visited_stage_ids", view)
        self.assertNotIn("stage_plan", view)
        self.assertEqual(view["started_stage_id"], "S3")
        self.assertNotIn("started_stage_name", view)
        self.assertNotIn("started_stage_order", view)
        self.assertNotIn("stage_statuses", view)
        self.assertEqual(view["completed_stage_ids"], ["S1"])
        flow_statuses = {item["stage_id"]: item["status"] for item in view["stage_flow"]}
        self.assertEqual(flow_statuses["S1"], "completed")
        self.assertEqual(flow_statuses["S3"], "active")
        self.assertEqual(flow_statuses["S4"], "pending")
        self.assertNotIn("stage_name", view["stage_flow"][0])
        self.assertNotIn("stage_name", view["stage_flow"][1])
        self.assertEqual(
            next(item for item in view["stage_flow"] if item["stage_id"] == "S3")["completed_main_question_ids"],
            [1, 4],
        )

    def test_interview_progress_can_restore_from_langgraph_checkpoint(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            await service.interview_agent.checkpoint_interview_progress(
                session_id="session-checkpoint",
                interview_progress={
                    "stage_id": "S3",
                    "completed": 0,
                    "completed_stage_ids": ["S1", "S2"],
                    "pending_stage_ids": ["S4"],
                    "pending_stage_mentions": {"S4": "退休后生活清闲了一些"},
                    "awaiting_stage_completion": 0,
                    "completed_main_question_ids": [1, 2],
                    "active_main_question_id": None,
                    "supplement_answered": 0,
                    "started_stage_id": "S1",
                    "stage_flow": [
                        {"stage_id": "S1", "status": "completed"},
                        {"stage_id": "S2", "status": "completed"},
                        {"stage_id": "S3", "status": "active", "completed_main_question_ids": [1, 2]},
                        {"stage_id": "S4", "status": "pending"},
                    ],
                },
            )

            restored = await service._get_or_create_interview_progress("session-checkpoint")

            self.assertEqual(restored["stage_id"], "S3")
            self.assertEqual(restored["completed_stage_ids"], ["S1", "S2"])
            self.assertEqual(restored["pending_stage_ids"], ["S4"])
            self.assertEqual(restored["completed_main_question_ids"], [1, 2])
            self.assertEqual(
                {item["stage_id"]: item["status"] for item in restored["stage_flow"]},
                {"S1": "completed", "S2": "completed", "S3": "active", "S4": "pending"},
            )

        asyncio.run(run_case())

    def test_resume_message_reuses_last_assistant_question(self) -> None:
        message = InterviewStateMachine._build_resume_message(
            {
                "stage_id": "S1",
                "completed": 0,
                "active_main_question_id": 4,
                "awaiting_stage_completion": 0,
            },
            [
                {"role": "assistant", "content": "除了家人，还有谁对您影响很深？"},
                {"role": "user", "content": "我想想。"},
            ],
        )

        self.assertIn("欢迎回来", message)
        self.assertIn("除了家人，还有谁对您影响很深？", message)

    def test_start_dialog_resumes_interviewing_session_without_new_opening(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            context = await service._create_context("session-resume")
            await service._transition(context, "INTERVIEWING")
            await service._set_interview_progress(
                "session-resume",
                {
                    "stage_id": "S1",
                    "completed": 0,
                    "completed_stage_ids": [],
                    "pending_stage_ids": [],
                    "pending_stage_mentions": {},
                    "cross_stage_mentions": [],
                    "cross_stage_current": None,
                    "awaiting_stage_completion": 0,
                    "completed_main_question_ids": [1, 2],
                    "active_main_question_id": 3,
                    "supplement_answered": 0,
                    "started_stage_id": "S1",
                    "stage_flow": [{"stage_id": "S1", "status": "active"}],
                },
            )
            await service._append_message("session-resume", "assistant", "小时候您最热衷做什么事？", stage_id="S1")

            response = await service.start_dialog("session-resume")

            self.assertEqual(response.action, "resume_interview")
            self.assertEqual(response.current_state, "INTERVIEWING")
            assert response.message is not None
            self.assertIn("小时候您最热衷做什么事？", response.message.content)

        asyncio.run(run_case())

    def test_legacy_redis_progress_is_migrated_to_langgraph_checkpoint(self) -> None:
        async def run_case() -> None:
            redis = MemoryRedis()
            service = InterviewStateMachine(redis)  # type: ignore[arg-type]
            legacy_progress = {
                "stage_id": "S3",
                "completed": 0,
                "completed_stage_ids": ["S1"],
                "pending_stage_ids": ["S4"],
                "pending_stage_mentions": {"S4": "retirement was calmer"},
                "awaiting_stage_completion": 0,
                "completed_main_question_ids": [1, 2, 3],
                "active_main_question_id": 3,
                "supplement_answered": 0,
                "started_stage_id": "S1",
                "stage_statuses": {"S1": "completed", "S3": "active", "S4": "pending"},
            }
            await redis.set(
                service._interview_progress_key("session-legacy"),
                json.dumps(legacy_progress, ensure_ascii=False),
            )

            restored = await service._get_or_create_interview_progress("session-legacy")
            checkpoint = await service.interview_agent.get_checkpointed_interview_progress("session-legacy")

            self.assertIsNotNone(checkpoint)
            assert checkpoint is not None
            self.assertEqual(restored["stage_id"], "S3")
            self.assertEqual(checkpoint["stage_id"], "S3")
            self.assertEqual(checkpoint["completed_stage_ids"], ["S1"])
            self.assertEqual(checkpoint["pending_stage_ids"], ["S4"])
            self.assertEqual(checkpoint["completed_main_question_ids"], [1, 2, 3])
            self.assertNotIn("stage_statuses", checkpoint)
            self.assertEqual(
                {item["stage_id"]: item["status"] for item in checkpoint["stage_flow"]},
                {"S1": "completed", "S3": "active", "S4": "pending"},
            )

        asyncio.run(run_case())

    def test_reset_interview_progress_replaces_checkpoint_with_initial_progress(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            await service.interview_agent.checkpoint_interview_progress(
                session_id="session-reset",
                interview_progress={
                    "stage_id": "S3",
                    "completed": 0,
                    "completed_stage_ids": ["S1", "S2"],
                    "pending_stage_ids": ["S4"],
                    "pending_stage_mentions": {"S4": "retirement was calmer"},
                    "awaiting_stage_completion": 0,
                    "completed_main_question_ids": [1, 2, 3],
                    "active_main_question_id": 3,
                    "supplement_answered": 0,
                    "started_stage_id": "S1",
                    "stage_flow": [
                        {"stage_id": "S1", "status": "completed"},
                        {"stage_id": "S2", "status": "completed"},
                        {"stage_id": "S3", "status": "active", "completed_main_question_ids": [1, 2, 3]},
                        {"stage_id": "S4", "status": "pending"},
                    ],
                },
            )

            await service._reset_interview_progress("session-reset")
            restored = await service._get_or_create_interview_progress("session-reset")
            checkpoint = await service.interview_agent.get_checkpointed_interview_progress("session-reset")

            self.assertIsNotNone(checkpoint)
            assert checkpoint is not None
            self.assertEqual(restored["stage_id"], "S1")
            self.assertEqual(checkpoint["stage_id"], "S1")
            self.assertEqual(checkpoint["completed_stage_ids"], [])
            self.assertEqual(checkpoint["pending_stage_ids"], [])
            self.assertEqual(checkpoint["completed_main_question_ids"], [])
            self.assertEqual(checkpoint["stage_flow"][0]["stage_id"], "S1")
            self.assertEqual(checkpoint["stage_flow"][0]["status"], "active")

        asyncio.run(run_case())

    def test_completed_stage_mention_is_not_added_to_pending_again(self) -> None:
        progress = {
            "stage_id": "S3",
            "remaining_rounds": 5,
            "completed": 0,
            "visited_stage_ids": ["S1"],
            "pending_stage_ids": [],
            "stage_statuses": {"S1": "completed", "S3": "active"},
        }
        detection = InterviewStageDetectionResult(stage_code="S1")

        updated = InterviewStateMachine._apply_detected_stage_mention(progress, detection, "小时候那段也说过了")

        self.assertEqual(updated["pending_stage_ids"], [])
        self.assertEqual(updated["stage_id"], "S3")

    def test_cross_stage_mention_is_stored_as_pending_stage(self) -> None:
        progress = {
            "stage_id": "S2",
            "completed": 0,
            "pending_stage_ids": [],
            "pending_stage_mentions": {},
            "cross_stage_mentions": [],
        }
        detection = InterviewStageDetectionResult(stage_code="S4")

        updated = InterviewStateMachine._apply_detected_stage_mention(
            progress,
            detection,
            "退休后我和老伴搬到南昌，每天一起散步。",
        )
        self.assertEqual(updated["stage_id"], "S2")
        self.assertEqual(updated["pending_stage_ids"], ["S4"])
        self.assertIn("S4", updated["pending_stage_mentions"])
        self.assertEqual(updated["cross_stage_current"]["stage_id"], "S4")
        self.assertEqual(updated["cross_stage_current"]["source_stage_id"], "S2")
        self.assertEqual(updated["cross_stage_mentions"][0]["stage_id"], "S4")

    def test_cross_stage_mentions_are_visible_and_marked_used_on_stage_switch(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S2",
                "completed": 0,
                "completed_stage_ids": [],
                "pending_stage_ids": ["S4"],
                "pending_stage_mentions": {"S4": "退休后我和老伴搬到南昌，每天一起散步。"},
                "cross_stage_mentions": [
                    {
                        "stage_id": "S4",
                        "source_stage_id": "S2",
                        "mention": "退休后我和老伴搬到南昌，每天一起散步。",
                        "created_at": "2026-06-14T00:00:00+00:00",
                        "used": False,
                    }
                ],
                "awaiting_stage_completion": 1,
                "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
                "active_main_question_id": 9,
            }

            view = InterviewStateMachine._hydrate_progress_view(progress)
            self.assertEqual(view["cross_stage_mentions"][0]["used"], False)

            answered = service._mark_active_main_question_answered(progress)
            updated = await service._complete_awaiting_stage_if_needed(context, answered)

            self.assertEqual(updated["stage_id"], "S4")
            self.assertEqual(updated["cross_stage_mentions"][0]["stage_id"], "S4")
            self.assertEqual(updated["cross_stage_mentions"][0]["used"], True)

        asyncio.run(run_case())

    def test_legacy_emotional_route_is_normalized_to_normal_interview(self) -> None:
        route = InterviewAgentService._parse_route(
            json.dumps(
                {
                    "route": "emotional_guidance",
                    "emotion_type": "unclear",
                    "confidence": 0.8,
                    "reason": "用户回复很短，需要降压。",
                    "should_change_topic": True,
                    "do_not_probe_current_topic": False,
                    "round_decrement": 1,
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(route.route, "normal_interview")
        self.assertTrue(route.needs_emotional_support)
        self.assertEqual(route.round_decrement, 1)

    def test_interview_progress_does_not_advance_when_round_decrement_is_zero(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S1",
                "remaining_rounds": 3,
                "completed": 0,
                "completed_main_question_ids": [1, 2, 3, 4, 5],
            }

            updated = await service._advance_interview_progress(context, progress, round_decrement=0)

            self.assertEqual(updated["stage_id"], "S1")
            self.assertNotIn("remaining_rounds", updated)
            self.assertEqual(InterviewStateMachine._remaining_main_question_count(updated), 3)
            self.assertEqual(updated["completed"], 0)

        asyncio.run(run_case())

    def test_interview_progress_waits_for_answer_before_stage_switch(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S1",
                "remaining_rounds": 1,
                "completed": 0,
                "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7],
                "active_main_question_id": 8,
            }

            answered = service._mark_active_main_question_answered(progress)
            updated = await service._advance_interview_progress(context, answered, round_decrement=1)

            self.assertEqual(updated["stage_id"], "S1")
            self.assertNotIn("remaining_rounds", updated)
            self.assertEqual(InterviewStateMachine._remaining_main_question_count(updated), 0)
            self.assertEqual(updated["completed"], 0)
            self.assertEqual(updated["awaiting_stage_completion"], 1)
            self.assertEqual(updated["completed_main_question_ids"], [1, 2, 3, 4, 5, 6, 7, 8])

        asyncio.run(run_case())

    def test_awaiting_stage_completion_stays_in_current_stage_for_supplement_prompt(self) -> None:
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
                "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
            }

            updated = await service._complete_awaiting_stage_if_needed(context, progress)

            self.assertEqual(updated["stage_id"], "S1")
            self.assertNotIn("remaining_rounds", updated)
            self.assertEqual(updated["completed"], 0)
            self.assertEqual(updated["awaiting_stage_completion"], 1)
            self.assertNotIn("visited_stage_ids", updated)
            self.assertEqual(updated["completed_stage_ids"], [])
            self.assertEqual(updated["completed_main_question_ids"], [1, 2, 3, 4, 5, 6, 7, 8])
            self.assertEqual(updated["stage_flow"][0]["stage_id"], "S1")
            self.assertEqual(updated["stage_flow"][0]["status"], "active")
            self.assertNotIn("stage_statuses", updated)

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
                "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
            }
            route = InterviewRouteResult(route="extended_interview", round_decrement=0)

            if int(progress.get("awaiting_stage_completion", 0)) and route.route != "extended_interview":
                progress = await service._complete_awaiting_stage_if_needed(context, progress)
            updated = await service._advance_interview_progress(context, progress, round_decrement=route.round_decrement)

            self.assertEqual(route.route, "extended_interview")
            self.assertEqual(updated["stage_id"], "S3")
            self.assertEqual(updated["awaiting_stage_completion"], 1)
            self.assertNotIn("remaining_rounds", updated)
            self.assertEqual(InterviewStateMachine._remaining_main_question_count(updated), 0)

        asyncio.run(run_case())

    def test_interview_progress_does_not_backfill_unvisited_stages_while_switching_disabled(self) -> None:
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
                "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
            }

            waiting = await service._advance_interview_progress(context, progress, round_decrement=1)
            updated = await service._complete_awaiting_stage_if_needed(context, waiting)

            self.assertEqual(updated["stage_id"], "S3")
            self.assertNotIn("remaining_rounds", updated)
            self.assertNotIn("visited_stage_ids", updated)
            self.assertEqual(updated["completed_stage_ids"], [])
            self.assertEqual(updated["awaiting_stage_completion"], 1)

        asyncio.run(run_case())

    def test_detected_stage_mention_is_recorded_but_not_prioritized_while_switching_disabled(self) -> None:
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
                "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
            }

            waiting = await service._advance_interview_progress(context, progress, round_decrement=1)
            updated = await service._complete_awaiting_stage_if_needed(context, waiting)

            self.assertEqual(updated["stage_id"], "S3")
            self.assertNotIn("remaining_rounds", updated)
            self.assertEqual(updated["pending_stage_ids"], ["S4"])
            self.assertNotIn("visited_stage_ids", updated)
            self.assertEqual(updated["completed_stage_ids"], [])

        asyncio.run(run_case())

    def test_pending_stage_context_is_kept_while_switching_disabled(self) -> None:
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
                "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
                "pending_stage_mentions": {"S4": "现在退休后倒是轻松多了"},
            }

            waiting = await service._advance_interview_progress(context, progress, round_decrement=1)
            updated = await service._complete_awaiting_stage_if_needed(context, waiting)
            description = InterviewStateMachine._stage_description(updated)

            self.assertEqual(updated["stage_id"], "S3")
            self.assertEqual(updated["pending_stage_mentions"]["S4"], "现在退休后倒是轻松多了")
            self.assertIn("流程衔接说明：当前处于人生转折阶段", description)
            self.assertNotIn("阶段切换衔接：无", description)

        asyncio.run(run_case())

    def test_supplement_answer_completion_moves_to_pending_stage(self) -> None:
        async def run_case() -> None:
            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            now = datetime.now(UTC)
            context = InterviewContext(session_id="session-1", state="INTERVIEWING", created_at=now, updated_at=now)
            progress = {
                "stage_id": "S3",
                "remaining_rounds": 0,
                "completed": 0,
                "visited_stage_ids": [],
                "pending_stage_ids": ["S4"],
                "pending_stage_mentions": {"S4": "现在退休后倒是轻松多了"},
                "awaiting_stage_completion": 1,
                "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
                "active_main_question_id": 9,
            }

            answered = service._mark_active_main_question_answered(progress)
            updated = await service._complete_awaiting_stage_if_needed(context, answered)

            self.assertEqual(updated["stage_id"], "S4")
            self.assertNotIn("remaining_rounds", updated)
            self.assertEqual(InterviewStateMachine._remaining_main_question_count(updated), 8)
            self.assertNotIn("visited_stage_ids", updated)
            self.assertEqual(updated["completed_stage_ids"], ["S3"])
            self.assertEqual(updated["completed_main_question_ids"], [])
            self.assertEqual(updated["supplement_answered"], 0)
            self.assertIn("岁月阅历", updated["stage_transition_hint"])
            self.assertNotIn("S4", updated["pending_stage_mentions"])

        asyncio.run(run_case())

    def test_stage_completion_keeps_turn_messages_in_completed_stage(self) -> None:
        async def run_case() -> None:
            class FakeParentGraph:
                async def run_turn(self, state: dict[str, object]) -> dict[str, object]:
                    self.state = state
                    progress = dict(state["progress"])  # type: ignore[arg-type]
                    return {
                        "progress": {
                            **progress,
                            "awaiting_stage_completion": 1,
                            "supplement_answered": 1,
                            "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
                        },
                        "stage_outcomes": {
                            "S3": {
                                "stage_id": "S3",
                                "summary": "讲清楚了事业转折。",
                                "bridge_hint": "承接到退休后的生活节奏。",
                            }
                        },
                        "stage_complete": True,
                        "stage_route": {"route": "stage_complete"},
                        "legacy_route_name": "normal_interview",
                        "assistant_message": "这一段我先帮您收束住。",
                        "response_source": "llm",
                    }

            async def no_checkpoint(*_: object, **__: object) -> None:
                return None

            async def no_checkpointed_progress(*_: object, **__: object) -> None:
                return None

            service = InterviewStateMachine(MemoryRedis())  # type: ignore[arg-type]
            service.interview_graph = FakeParentGraph()  # type: ignore[assignment]
            service.interview_agent.checkpoint_interview_progress = no_checkpoint  # type: ignore[method-assign]
            service.interview_agent.get_checkpointed_interview_progress = no_checkpointed_progress  # type: ignore[method-assign]
            context = await service._create_context("session-stage-complete")
            await service._transition(context, "INTERVIEWING")
            await service._set_interview_progress(
                context.session_id,
                {
                    "stage_id": "S3",
                    "completed": 0,
                    "completed_stage_ids": ["S1", "S2"],
                    "pending_stage_ids": ["S4"],
                    "pending_stage_mentions": {},
                    "cross_stage_mentions": [],
                    "cross_stage_current": None,
                    "awaiting_stage_completion": 1,
                    "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
                    "active_main_question_id": 9,
                    "supplement_answered": 0,
                    "stage_flow": [
                        {"stage_id": "S1", "status": "completed"},
                        {"stage_id": "S2", "status": "completed"},
                        {"stage_id": "S3", "status": "active"},
                        {"stage_id": "S4", "status": "pending"},
                    ],
                    "stage_outcomes": {},
                },
            )

            response = await service.handle_dialog_text(
                DialogTextRequest(session_id=context.session_id, content="这段没有其他补充了。")
            )
            messages = await service._get_messages(context.session_id)

            self.assertEqual(response.state_interview["stage_id"], "S4")
            self.assertIn("承接到退休后的生活节奏", response.state_interview["stage_transition_hint"])
            self.assertEqual([message["stage_id"] for message in messages], ["S3", "S3"])

        asyncio.run(run_case())

    def test_route_transition_hint_is_prompt_visible(self) -> None:
        progress = {
            "stage_id": "S2",
            "remaining_rounds": 6,
            "completed": 0,
            "stage_transition_hint": "",
        }

        updated = InterviewStateMachine._set_turn_transition_hint(
            progress,
            route_name="extended_interview",
            history=[{"role": "user", "content": "以前练拳的时候师父很照顾我"}],
        )
        description = InterviewStateMachine._stage_description(updated)

        self.assertIn("流程衔接说明：当前仍在青春岁月阶段，本轮路由为扩展追问", description)
        self.assertIn("阶段切换衔接：当前仍在青春岁月阶段，本轮路由为扩展追问", description)

    def test_completed_stages_are_not_reopened_while_switching_disabled(self) -> None:
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
                "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
            }

            waiting = await service._advance_interview_progress(context, progress, round_decrement=1)
            updated = await service._complete_awaiting_stage_if_needed(context, waiting)

            self.assertEqual(updated["stage_id"], "S1")
            self.assertNotIn("visited_stage_ids", updated)
            self.assertEqual(updated["completed_stage_ids"], ["S3"])
            self.assertNotIn("stage_statuses", updated)
            flow_statuses = {item["stage_id"]: item["status"] for item in updated["stage_flow"]}
            self.assertEqual(flow_statuses["S3"], "completed")
            self.assertEqual(flow_statuses["S1"], "active")
            self.assertNotIn("S2", flow_statuses)
            description = InterviewStateMachine._stage_description(updated)
            self.assertIn("编号 9 的补充询问", description)

        asyncio.run(run_case())

    def test_final_stage_completes_after_supplement_answer(self) -> None:
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
                "completed_main_question_ids": [1, 2, 3, 4, 5, 6, 7, 8],
                "active_main_question_id": 9,
            }

            answered = service._mark_active_main_question_answered(progress)
            updated = await service._complete_awaiting_stage_if_needed(context, answered)

            self.assertEqual(updated["completed"], 1)
            self.assertEqual(updated["awaiting_stage_completion"], 0)
            self.assertNotIn("visited_stage_ids", updated)
            self.assertEqual(updated["completed_stage_ids"], ["S1", "S2", "S3", "S4", "S5"])
            self.assertEqual(updated["stage_id"], "S5")

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
