import asyncio
import json
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.core.llm_client import interview_llm
from app.core.perf import perf_span
from app.prompts.loader import load_prompt
from app.prompts.interview_prompts import (
    EMOTION_BASE_PROMPT,
    EMOTION_PROMPT_BY_TYPE,
    ICEBREAKER_PROMPT,
    ROUTING_JUDGEMENT_PROMPT,
    STAGE_ROUTE_PROMPT,
    STAGE_SUMMARY_PROMPT,
    STAGE_MAIN_QUESTION_IDS,
    STAGE_PROMPT_FILES,
)

TurnGraphNextNode = Literal[
    "normal_reply",
    "extended_reply",
]
RouteName = Literal[
    "normal_interview",
    "extended_interview",
    "emotional_guidance",
]
StageRouteName = Literal[
    "normal_answer",
    "extended_probe",
    "low_information",
    "off_stage_reference",
    "stage_complete",
    "emotional_blocked",
]

VALID_STAGE_IDS = {*STAGE_MAIN_QUESTION_IDS.keys(), "unclear"}
FORMAL_STAGE_IDS = tuple(STAGE_MAIN_QUESTION_IDS.keys())
STAGE_NAME_BY_ID = {
    "S1": "童年时光",
    "S2": "青春岁月",
    "S3": "人生转折",
    "S4": "岁月阅历",
    "S5": "收尾总结",
    "unclear": "未识别",
}
STAGE_NAME_BY_ID.update(
    {
        "S1": "童年底色",
        "S2": "青春启蒙",
        "S3": "事业起步与初心",
        "S4": "关键转折与破局",
        "S5": "巅峰与至暗",
        "S6": "平衡与取舍",
        "S7": "当下与未来传承",
        "unclear": "未识别",
    }
)
MAIN_QUESTION_IDS = tuple(
    range(1, max(max(ids) for ids in STAGE_MAIN_QUESTION_IDS.values()) + 1)
)
SUPPLEMENT_QUESTION_ID = 9
FOLLOWUP_EXHAUSTED_REPLY = "当前主问题所有追问已完成"
EMOTIONAL_SUPPORT_TYPES = {
    "sadness",
    "regret_self_blame",
    "repression_grievance",
    "anxiety_heavy",
    "loneliness",
    "mixed",
}
REPLY_NODE_BY_ROUTE: dict[RouteName, TurnGraphNextNode] = {
    "normal_interview": "normal_reply",
    "extended_interview": "extended_reply",
    "emotional_guidance": "normal_reply",
}
ROUND_DECREMENT_BY_ROUTE: dict[RouteName, int] = {
    "normal_interview": 1,
    "extended_interview": 0,
    "emotional_guidance": 1,
}

MAX_HISTORY_MESSAGES = 8
MAX_HISTORY_MESSAGE_CHARS = 500
NORMAL_PROMPT_INPUT_REPLACEMENTS = {
    "{{历史对话}}": "history",
    "{{当前阶段描述}}": "stage_description",
    "{{当前阶段建议剩余轮数}}": "remaining_rounds",
    "{{当前阶段已问主问题编号}}": "completed_main_question_ids",
    "{{当前阶段已收集主问题编号}}": "completed_main_question_ids",
    "{{用户本轮输入}}": "user_message",
    "{{路由判断结果}}": "route_json",
}
NORMAL_INTERVIEW_SECTIONS = (
    "## 基础提示词",
    "## 普通轮次节奏提示词",
    "## 阶段收束提示词",
    "## 输入区",
)
class InterviewRouteResult(BaseModel):
    route: RouteName = "normal_interview"
    emotion_type: str = "none"
    needs_emotional_support: bool = False
    confidence: float = 0.0
    reason: str = ""
    should_change_topic: bool = False
    do_not_probe_current_topic: bool = False
    round_decrement: int = Field(default=1, ge=0, le=1)


class InterviewStageDetectionResult(BaseModel):
    stage_code: str = "unclear"
    stage_name: str = "未识别"
    judgment_reason: str = ""


class InterviewStageRouteResult(BaseModel):
    route: StageRouteName = "normal_answer"
    confidence: float = 0.0
    reason: str = ""
    missing_info: list[str] = Field(default_factory=list)
    requested_stage_jump: str | None = None
    can_probe: bool = True


class InterviewTurnResult(BaseModel):
    reply: str
    route: InterviewRouteResult
    response_source: Literal["llm"] = "llm"
    main_question_id: int | None = Field(default=None, ge=1, le=9)


class InterviewReplyResult(BaseModel):
    reply: str
    main_question_id: int | None = Field(default=None, ge=1, le=9)


class InterviewOpeningResult(BaseModel):
    reply: str
    response_source: Literal["llm"] = "llm"


class InterviewTurnGraphState(TypedDict, total=False):
    session_id: str
    interview_progress: dict[str, Any]
    user_message: str
    recent_messages: list[dict[str, str]]
    stage_description: str
    remaining_rounds: int
    completed_main_question_ids: list[int]
    route: dict[str, Any]
    reply: str
    response_source: Literal["llm"]
    main_question_id: int | None


class InterviewAgentService:
    def __init__(self, checkpointer: Any | None = None) -> None:
        self._turn_graph = self._build_turn_graph(checkpointer=checkpointer)

    async def generate_icebreaker(
        self,
        *,
        recent_messages: list[dict[str, str]],
        stage_description: str,
    ) -> InterviewOpeningResult:
        with perf_span("interview.icebreaker.total", history=len(recent_messages)):
            prompt = load_prompt(ICEBREAKER_PROMPT)
            raw = await asyncio.to_thread(
                interview_llm.chat,
                prompt,
                f"当前阶段：{stage_description}\n请生成一句自然的开场追问。",
                temperature=0.5,
                max_tokens=256,
            )
            return InterviewOpeningResult(reply=raw, response_source="llm")

    async def generate_turn(
        self,
        *,
        user_message: str,
        recent_messages: list[dict[str, str]],
        stage_description: str,
        remaining_rounds: int,
        completed_main_question_ids: list[int] | None = None,
        session_id: str | None = None,
        interview_progress: dict[str, Any] | None = None,
    ) -> InterviewTurnResult:
        with perf_span("interview.turn.total", chars=len(user_message), history=len(recent_messages)):
            state = await self._turn_graph.ainvoke(
                {
                    "session_id": session_id or "",
                    "interview_progress": interview_progress or {},
                    "user_message": user_message,
                    "recent_messages": recent_messages,
                    "stage_description": stage_description,
                    "remaining_rounds": remaining_rounds,
                    "completed_main_question_ids": completed_main_question_ids or [],
                },
                self._graph_config(session_id),
            )
            return InterviewTurnResult(
                reply=state["reply"],
                route=self._route_from_state(state),
                response_source=state.get("response_source", "llm"),
                main_question_id=state.get("main_question_id"),
            )

    async def judge_stage_route(
        self,
        *,
        user_message: str,
        local_messages: list[dict[str, str]],
        stage_description: str,
        remaining_rounds: int,
    ) -> InterviewStageRouteResult:
        prompt = self._extract_text_block(self._load_interview_prompt(STAGE_ROUTE_PROMPT))
        prompt = (
            prompt.replace("{{stage_description}}", stage_description)
            .replace("{{local_history}}", self._format_history(local_messages, limit=None))
            .replace("{{remaining_rounds}}", str(max(0, remaining_rounds)))
            .replace("{{user_message}}", user_message)
        )
        with perf_span("llm.interview.stage_route", model=interview_llm.model, chars=len(user_message)):
            raw = await asyncio.to_thread(
                interview_llm.chat,
                "你只输出严格 JSON，不输出 Markdown。",
                prompt,
                temperature=0.1,
                max_tokens=512,
            )
        return self._parse_stage_route(raw)

    async def generate_low_information_reply(
        self,
        *,
        user_message: str,
        local_messages: list[dict[str, str]],
        stage_description: str,
    ) -> str:
        prompt = "\n".join(
            [
                "你是温和的人生故事采访者。",
                "用户当前回复信息量较低，请不要批评、不要追问过多。",
                "请先降低压力，再给出一个更小、更容易回答的入口问题。",
                "只输出一句自然口语化采访回复，不要输出解释。",
                "",
                f"当前阶段：{stage_description}",
                f"阶段内历史：{self._format_history(local_messages, limit=6)}",
                f"用户回复：{user_message}",
            ]
        )
        with perf_span("llm.interview.low_information_reply", model=interview_llm.model, chars=len(user_message)):
            raw = await asyncio.to_thread(
                interview_llm.chat,
                "你只输出采访者下一句话。",
                prompt,
                temperature=0.5,
                max_tokens=256,
            )
        return self._normalize_reply(raw)

    async def summarize_stage(
        self,
        *,
        stage_id: str,
        stage_description: str,
        local_messages: list[dict[str, str]],
        global_outline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt = self._extract_text_block(self._load_interview_prompt(STAGE_SUMMARY_PROMPT))
        prompt = (
            prompt.replace("{{stage_id}}", stage_id)
            .replace("{{stage_description}}", stage_description)
            .replace("{{local_history}}", self._format_history(local_messages, limit=None))
            .replace("{{global_outline}}", json.dumps(global_outline or {}, ensure_ascii=False))
        )
        with perf_span("llm.interview.stage_summary", model=interview_llm.model, messages=len(local_messages)):
            raw = await asyncio.to_thread(
                interview_llm.chat,
                "你只输出严格 JSON，不输出 Markdown。",
                prompt,
                temperature=0.2,
                max_tokens=512,
            )
        return self._parse_stage_outcome(raw, stage_id=stage_id)

    async def generate_reply_for_route(
        self,
        *,
        route: InterviewRouteResult,
        user_message: str,
        recent_messages: list[dict[str, str]],
        stage_description: str,
        remaining_rounds: int,
        completed_main_question_ids: list[int] | None = None,
        session_id: str | None = None,
        interview_progress: dict[str, Any] | None = None,
    ) -> tuple[str, Literal["llm"], int | None]:
        route = self._normalize_active_route(route)
        state: InterviewTurnGraphState = {
            "route": self._route_to_state(route),
            "session_id": session_id or "",
            "interview_progress": interview_progress or {},
            "user_message": user_message,
            "recent_messages": recent_messages,
            "stage_description": stage_description,
            "remaining_rounds": remaining_rounds,
            "completed_main_question_ids": completed_main_question_ids or [],
            "response_source": "llm",
        }
        result = await self._turn_graph.ainvoke(state, self._graph_config(session_id))
        if route.route == "extended_interview" and result["reply"].strip() == FOLLOWUP_EXHAUSTED_REPLY:
            normal_route = route.model_copy(update={"route": "normal_interview", "round_decrement": 1})
            state["route"] = self._route_to_state(normal_route)
            result = await self._turn_graph.ainvoke(state, self._graph_config(session_id))
        return result["reply"], result.get("response_source", "llm"), result.get("main_question_id")

    async def checkpoint_interview_progress(
        self,
        *,
        session_id: str,
        interview_progress: dict[str, Any],
    ) -> None:
        await self._turn_graph.aupdate_state(
            self._graph_config(session_id),
            {
                "session_id": session_id,
                "interview_progress": interview_progress,
            },
            as_node="normal_reply",
        )

    async def get_checkpointed_interview_progress(self, session_id: str) -> dict[str, Any] | None:
        snapshot = await self._turn_graph.aget_state(self._graph_config(session_id))
        progress = snapshot.values.get("interview_progress")
        return progress if isinstance(progress, dict) else None

    async def delete_checkpoint_thread(self, session_id: str) -> None:
        checkpointer = getattr(self._turn_graph, "checkpointer", None)
        if checkpointer is None:
            return
        await checkpointer.adelete_thread(f"interview-turn:{session_id}")

    def _reply_handlers(self) -> dict[TurnGraphNextNode, Any]:
        return {
            "normal_reply": self._normal_reply_turn,
            "extended_reply": self._extended_reply_turn,
        }

    async def _llm_route_turn(self, state: InterviewTurnGraphState) -> InterviewTurnGraphState:
        if "route" in state:
            route = self._route_from_state(state)
            return {
                "route": self._route_to_state(self._apply_stage_route_rules(route, state["stage_description"])),
                "response_source": state.get("response_source", "llm"),
            }
        route = await self._judge_route(
            state["user_message"],
            state["recent_messages"],
            state["remaining_rounds"],
        )
        return {
            "route": self._route_to_state(self._apply_stage_route_rules(route, state["stage_description"])),
            "response_source": "llm",
        }

    def _build_turn_graph(self, *, checkpointer: Any | None = None) -> Any:
        graph = StateGraph(InterviewTurnGraphState)
        graph.add_node("route", self._route_turn)
        graph.add_node("normal_reply", self._normal_reply_turn)
        graph.add_node("extended_reply", self._extended_reply_turn)
        graph.set_entry_point("route")
        graph.add_conditional_edges(
            "route",
            self._select_reply_node,
            {
                "normal_reply": "normal_reply",
                "extended_reply": "extended_reply",
            },
        )
        graph.add_edge("normal_reply", END)
        graph.add_edge("extended_reply", END)
        return graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _graph_config(session_id: str | None) -> dict[str, dict[str, str]]:
        if not session_id:
            return {"configurable": {"thread_id": f"interview-turn:ephemeral:{uuid4()}"}}
        return {"configurable": {"thread_id": f"interview-turn:{session_id}"}}

    async def _route_turn(self, state: InterviewTurnGraphState) -> InterviewTurnGraphState:
        return await self._llm_route_turn(state)

    @staticmethod
    def _select_reply_node(state: InterviewTurnGraphState) -> TurnGraphNextNode:
        return REPLY_NODE_BY_ROUTE[InterviewAgentService._route_from_state(state).route]

    async def _normal_reply_turn(self, state: InterviewTurnGraphState) -> InterviewTurnGraphState:
        return await self._llm_reply_turn(state)

    async def _extended_reply_turn(self, state: InterviewTurnGraphState) -> InterviewTurnGraphState:
        return await self._llm_reply_turn(state)

    async def _llm_reply_turn(self, state: InterviewTurnGraphState) -> InterviewTurnGraphState:
        route = self._route_from_state(state)
        user_message = state["user_message"]
        recent_messages = state["recent_messages"]
        stage_description = state["stage_description"]
        remaining_rounds = state["remaining_rounds"]
        completed_main_question_ids = state.get("completed_main_question_ids", [])

        result = await self._generate_reply(
            route=route,
            user_message=user_message,
            recent_messages=recent_messages,
            stage_description=stage_description,
            remaining_rounds=remaining_rounds,
            completed_main_question_ids=completed_main_question_ids,
        )
        return {
            "reply": result.reply,
            "response_source": "llm",
            "main_question_id": result.main_question_id,
        }

    @staticmethod
    def _route_to_state(route: InterviewRouteResult) -> dict[str, Any]:
        return route.model_dump(mode="json")

    @staticmethod
    def _route_from_state(state: InterviewTurnGraphState) -> InterviewRouteResult:
        route = state["route"]
        if isinstance(route, InterviewRouteResult):
            return route
        return InterviewRouteResult.model_validate(route)

    async def _judge_route(
        self,
        user_message: str,
        recent_messages: list[dict[str, str]],
        remaining_rounds: int,
    ) -> InterviewRouteResult:
        prompt = self._extract_text_block(self._load_interview_prompt(ROUTING_JUDGEMENT_PROMPT))
        prompt = (
            prompt.replace("{{历史对话}}", self._format_history(recent_messages))
            .replace("{{当前阶段建议剩余轮数}}", str(max(0, remaining_rounds)))
            .replace("{{用户本轮回复}}", user_message)
        )
        with perf_span("llm.interview.route", model=interview_llm.model, chars=len(user_message)):
            raw = await asyncio.to_thread(
                interview_llm.chat,
                "你只输出严格 JSON，不输出 Markdown。",
                prompt,
                temperature=0.2,
                max_tokens=512,
            )
        return self._parse_route(raw)

    async def _generate_reply(
        self,
        *,
        route: InterviewRouteResult,
        user_message: str,
        recent_messages: list[dict[str, str]],
        stage_description: str,
        remaining_rounds: int,
        completed_main_question_ids: list[int],
    ) -> InterviewReplyResult:
        prompt = self._build_reply_prompt(
            route,
            user_message,
            recent_messages,
            stage_description,
            remaining_rounds,
            completed_main_question_ids,
        )
        with perf_span(
            "llm.interview.reply",
            model=interview_llm.model,
            route=route.route,
            chars=len(user_message),
        ):
            raw = await asyncio.to_thread(
                interview_llm.chat,
                self._reply_system_prompt(route),
                prompt,
                temperature=0.7,
                max_tokens=512,
            )
        if route.route == "normal_interview":
            return self._parse_main_question_reply(
                raw,
                allow_supplement=remaining_rounds == 0,
                stage_id=self._stage_id_from_description(stage_description),
            )
        return InterviewReplyResult(reply=self._normalize_reply(raw))

    def _build_reply_prompt(
        self,
        route: InterviewRouteResult,
        user_message: str,
        recent_messages: list[dict[str, str]],
        stage_description: str,
        remaining_rounds: int,
        completed_main_question_ids: list[int] | None = None,
    ) -> str:
        completed_ids = self._valid_main_question_ids(completed_main_question_ids or [])
        values = {
            "history": self._format_history(recent_messages, limit=None),
            "stage_description": stage_description,
            "remaining_rounds": str(max(0, remaining_rounds)),
            "completed_main_question_ids": self._format_main_question_ids(completed_ids),
            "user_message": user_message,
            "route_json": route.model_dump_json(ensure_ascii=False),
        }
        stage_id = self._stage_id_from_description(stage_description)
        prompt_builders = {
            "normal_interview": lambda: (
                self._build_main_question_prompt(
                    self._prompt_file_for_stage(stage_id, "main_question"),
                    remaining_rounds,
                ),
                NORMAL_PROMPT_INPUT_REPLACEMENTS,
            ),
            "extended_interview": lambda: (
                self._extract_text_block(
                    self._load_interview_prompt(
                        self._prompt_file_for_stage(stage_id, "followup")
                    )
                ),
                NORMAL_PROMPT_INPUT_REPLACEMENTS,
            ),
        }
        prompt, replacements = prompt_builders[route.route]()
        prompt = self._append_emotional_support_prompt(prompt, route)
        return self._fill_prompt(prompt, replacements, values)

    def _build_main_question_prompt(self, prompt_name: str, remaining_rounds: int) -> str:
        doc = self._load_interview_prompt(prompt_name)
        if not all(title in doc for title in NORMAL_INTERVIEW_SECTIONS):
            return self._extract_text_block(doc)
        base, normal, low_round, input_block = (
            self._section_code_block(doc, title) for title in NORMAL_INTERVIEW_SECTIONS
        )
        rhythm = normal if remaining_rounds > 1 else low_round
        return "\n\n".join([base, rhythm, input_block])

    @staticmethod
    def _reply_system_prompt(route: InterviewRouteResult) -> str:
        if route.route == "normal_interview":
            return (
                "你是一位温和的纪实采访者。只输出严格 JSON，不输出 Markdown。"
                "JSON 必须包含 question_id 和 question；question_id 是 1 到 8 的整数，"
                "只有当前阶段 8 个主问题都已完成时才允许输出 9。"
            )
        return "你是一位温和的纪实采访者。只输出一句采访话术，不要添加“采：”或任何说话人前缀。"

    @staticmethod
    def _parse_main_question_reply(
        raw: str,
        *,
        allow_supplement: bool = False,
        stage_id: str = "unclear",
    ) -> InterviewReplyResult:
        data: dict[str, Any] = json.loads(raw.strip())
        reply = data.get("reply", data.get("question"))
        raw_question_id = data.get("question_id", data.get("question_number", data.get("main_question_id")))
        valid_ids = InterviewAgentService._main_question_ids_for_stage(stage_id)
        valid_label = f"{valid_ids[0]} to {valid_ids[-1]}" if valid_ids else "the current stage range"
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("Main question reply JSON must include a non-empty reply/question string.")
        if isinstance(raw_question_id, bool):
            raise ValueError(f"Main question id must be an integer from {valid_label}, or 9 in supplement mode.")
        try:
            question_id = int(raw_question_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Main question id must be an integer from {valid_label}, or 9 in supplement mode.") from exc
        if allow_supplement and question_id == SUPPLEMENT_QUESTION_ID:
            return InterviewReplyResult(
                reply=InterviewAgentService._normalize_reply(reply),
                main_question_id=SUPPLEMENT_QUESTION_ID,
            )
        if question_id not in valid_ids:
            raise ValueError(f"Main question id must be an integer from {valid_label}, or 9 in supplement mode.")
        return InterviewReplyResult(reply=InterviewAgentService._normalize_reply(reply), main_question_id=question_id)

    @staticmethod
    def _parse_route(raw: str) -> InterviewRouteResult:
        data: dict[str, Any] = json.loads(raw.strip())
        route = InterviewRouteResult.model_validate(data)
        route = InterviewAgentService._normalize_active_route(route)
        route.needs_emotional_support = InterviewAgentService._route_needs_emotional_support(route)
        route.round_decrement = ROUND_DECREMENT_BY_ROUTE[route.route]
        return route

    @staticmethod
    def _normalize_active_route(route: InterviewRouteResult) -> InterviewRouteResult:
        if route.route == "emotional_guidance":
            route = route.model_copy(
                update={
                    "route": "normal_interview",
                    "needs_emotional_support": True,
                }
            )
        return route

    @staticmethod
    def _route_needs_emotional_support(route: InterviewRouteResult) -> bool:
        if route.needs_emotional_support:
            return True
        if route.emotion_type in EMOTIONAL_SUPPORT_TYPES:
            return True
        return False

    @staticmethod
    def _append_emotional_support_prompt(prompt: str, route: InterviewRouteResult) -> str:
        if not route.needs_emotional_support:
            return prompt
        base_prompt = InterviewAgentService._extract_text_block(
            InterviewAgentService._load_interview_prompt(EMOTION_BASE_PROMPT)
        )
        emotion_prompt = InterviewAgentService._extract_text_block(
            InterviewAgentService._load_interview_prompt(
                InterviewAgentService._emotion_prompt_for_type(route.emotion_type)
            )
        )
        return "\n\n".join(
            [
                prompt,
                "## 情绪安慰融合规则",
                "以下规则仅用于把轻量安慰融合进当前采访或扩展追问中，不启用独立情绪疏导路线。",
                "必须保持当前提示词原本的输出格式：",
                "- 当前是 normal_interview 时，仍然只输出包含 question_id 和 question 的 JSON；把安慰放进 question 字段的开头承接里。",
                "- 当前是 extended_interview 时，仍然只输出一句采访话术；先安慰，再围绕当前素材问一个低压力开放问题。",
                "不要输出“情绪疏导、路由、策略”等内部词。",
                base_prompt,
                "## 针对性情绪规则",
                emotion_prompt,
            ]
        )

    @staticmethod
    def _emotion_prompt_for_type(emotion_type: str) -> str:
        return EMOTION_PROMPT_BY_TYPE.get(emotion_type, EMOTION_PROMPT_BY_TYPE["unclear"])

    @staticmethod
    def _parse_stage_route(raw: str) -> InterviewStageRouteResult:
        data: dict[str, Any] = json.loads(raw.strip())
        result = InterviewStageRouteResult.model_validate(data)
        if result.requested_stage_jump not in VALID_STAGE_IDS:
            result.requested_stage_jump = None
        result.reason = result.reason.strip()[:120]
        result.missing_info = [str(item).strip()[:80] for item in result.missing_info if str(item).strip()][:6]
        return result

    @staticmethod
    def _parse_stage_outcome(raw: str, *, stage_id: str) -> dict[str, Any]:
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            data = {"summary": raw.strip()}
        if not isinstance(data, dict):
            data = {"summary": str(data)}

        def clean_list(value: Any, limit: int = 8) -> list[str]:
            if not isinstance(value, list):
                return []
            return [str(item).strip()[:120] for item in value if str(item).strip()][:limit]

        return {
            "stage_id": stage_id,
            "summary": str(data.get("summary") or "").strip()[:240],
            "key_events": clean_list(data.get("key_events")),
            "key_people": clean_list(data.get("key_people")),
            "emotional_notes": clean_list(data.get("emotional_notes")),
            "unresolved_threads": clean_list(data.get("unresolved_threads")),
            "bridge_hint": str(data.get("bridge_hint") or "").strip()[:160],
        }

    @staticmethod
    def _parse_stage_detection(raw: str) -> InterviewStageDetectionResult:
        data: dict[str, Any] = json.loads(raw.strip())
        result = InterviewStageDetectionResult.model_validate(data)
        result.stage_code = result.stage_code if result.stage_code in VALID_STAGE_IDS else "unclear"
        result.stage_name = STAGE_NAME_BY_ID.get(result.stage_code, result.stage_name or result.stage_code)
        result.judgment_reason = result.judgment_reason.strip()[:80]
        return result

    @staticmethod
    def _apply_stage_route_rules(route: InterviewRouteResult, stage_description: str) -> InterviewRouteResult:
        return route

    @staticmethod
    def _stage_id_from_description(stage_description: str) -> str:
        for stage_id in FORMAL_STAGE_IDS:
            if f"阶段：{stage_id}" in stage_description:
                return stage_id
        return "unclear"

    @staticmethod
    def _prompt_file_for_stage(stage_id: str, prompt_type: str) -> str:
        prompt_file = STAGE_PROMPT_FILES.get(stage_id, {}).get(prompt_type)
        if not prompt_file:
            raise ValueError(f"Stage prompt not configured: stage={stage_id}, prompt_type={prompt_type}")
        return prompt_file

    @staticmethod
    def _valid_main_question_ids(value: list[int]) -> list[int]:
        result: list[int] = []
        for item in value:
            if isinstance(item, bool):
                continue
            try:
                question_id = int(item)
            except (TypeError, ValueError):
                continue
            if question_id in MAIN_QUESTION_IDS and question_id not in result:
                result.append(question_id)
        return result

    @staticmethod
    def _main_question_ids_for_stage(stage_id: str) -> tuple[int, ...]:
        return STAGE_MAIN_QUESTION_IDS.get(stage_id, MAIN_QUESTION_IDS)

    @staticmethod
    def _format_main_question_ids(question_ids: list[int]) -> str:
        ids = InterviewAgentService._valid_main_question_ids(question_ids)
        return "无" if not ids else "、".join(str(question_id) for question_id in ids)

    @staticmethod
    def _format_history(messages: list[dict[str, str]], *, limit: int | None = MAX_HISTORY_MESSAGES) -> str:
        if not messages:
            return "暂无历史对话。"
        lines: list[str] = []
        scoped_messages = messages if limit is None else messages[-limit:]
        for msg in scoped_messages:
            role = "采" if msg.get("role") == "assistant" else "受"
            content = str(msg.get("content") or "").strip()[:MAX_HISTORY_MESSAGE_CHARS]
            if content:
                lines.append(f"{role}：{content}")
        return "\n".join(lines) if lines else "暂无历史对话。"

    @staticmethod
    def _normalize_reply(raw: str) -> str:
        text = raw.strip().strip('"')
        for prefix in ("采：", "采:", "采访者：", "采访者:", "采访官：", "采访官:"):
            if text.startswith(prefix):
                return text[len(prefix) :].strip()
        return text

    @staticmethod
    def _fill_prompt(prompt: str, replacements: dict[str, str], values: dict[str, str]) -> str:
        for placeholder, value_key in replacements.items():
            if isinstance(value_key, str) and value_key in values:
                prompt = prompt.replace(placeholder, values[value_key])
            else:
                prompt = prompt.replace(placeholder, str(value_key).format(**values))
        return prompt

    @staticmethod
    def _load_interview_prompt(name: str) -> str:
        return load_prompt(name)

    @staticmethod
    def _extract_text_block(markdown: str) -> str:
        marker = "```text"
        if marker not in markdown:
            return markdown.strip()
        tail = markdown.split(marker, 1)[1]
        if "```" not in tail:
            return tail.strip()
        return tail.split("```", 1)[0].strip()

    @staticmethod
    def _section_code_block(markdown: str, section_title: str) -> str:
        start = markdown.find(section_title)
        if start < 0:
            raise ValueError(f"Section not found: {section_title}")
        tail = markdown[start:]
        block = InterviewAgentService._extract_text_block(tail)
        if block == tail.strip():
            raise ValueError(f"Text block not found in section: {section_title}")
        return block
