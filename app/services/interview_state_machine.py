import json
from datetime import UTC, datetime
from typing import Any, cast, get_args
from uuid import uuid4

from redis.asyncio import Redis

from app.core.config import settings
from app.core.perf import perf_span
from app.data.interview_cards import normalize_card_id
from app.data.interview_stage_config import (
    FIRST_INTERVIEW_STAGE,
    INTERVIEW_STAGE_BY_ID,
    INTERVIEW_STAGE_IDS,
    REMOVED_PROGRESS_FIELDS,
    STAGE_STATUS_VALUES,
)
from app.graphs.interview_parent_graph import InterviewParentGraph
from app.graphs.interview_stage_runtime import InterviewStageRuntime, SUPPLEMENT_QUESTION_ID
from app.schemas.interview import (
    DialogActionRequest,
    DialogMessage,
    DialogTextRequest,
    DialogTurnResponse,
    InterviewContext,
    InterviewState,
    InterviewStateResponse,
    UserInfoRequest,
    UserInfoResponse,
)
from app.services.dashscope_llm import DashScopeLLM
from app.services.interview_agent_service import (
    InterviewAgentService,
    InterviewStageDetectionResult,
)
from app.services.langgraph_redis_checkpoint import RedisCheckpointSaver
from app.services.opening_service import OpeningService
from app.services.interview_session_store import InterviewSessionStore

VALID_INTERVIEW_STATES = set(get_args(InterviewState))


class InterviewStateMachine:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.store = InterviewSessionStore(redis, settings.session_ttl_seconds)
        self.guidance_llm = DashScopeLLM()
        checkpointer = RedisCheckpointSaver(redis)
        self.interview_agent = InterviewAgentService(checkpointer=checkpointer)
        self.interview_graph = InterviewParentGraph(self.interview_agent, checkpointer=checkpointer)
        self.opening = OpeningService()

    async def start_dialog(self, session_id: str | None = None, user_id: str | None = None) -> DialogTurnResponse:
        """创建/恢复会话，返回元数据（不含开场白文本，开场白由 stream_opening 流式输出）。"""
        # 记录时间
        with perf_span("dialog.start", has_session=bool(session_id)):
            context = await self._get_or_create_context(session_id)
            if session_id and self._current_state(context) == "INTERVIEWING":
                return await self._resume_interview_dialog(context)
            await self._transition(context, "OPENING_GENERATING")
            await self._transition(context, "OPENING_DELIVERED")

        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=self._current_state(context),
            previous_state=context.previous_state,
            action="append_message",
            message=None,
            response_source="none",
            state_interview=await self._get_or_create_interview_progress(context.session_id),
        )

    async def save_opening_message(self, session_id: str, content: str) -> None:
        """将完整的开场白文本存入消息历史。"""
        await self._append_message(session_id, "assistant", content)

    async def _resume_interview_dialog(self, context: InterviewContext) -> DialogTurnResponse:
        progress = await self._get_or_create_interview_progress(context.session_id)
        messages = await self._get_messages(context.session_id)
        resume_message = self._build_resume_message(progress, messages)
        context.updated_at = datetime.now(UTC)
        await self._save_state(context)
        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=self._current_state(context),
            previous_state=context.previous_state,
            action="resume_interview",
            message=DialogMessage(content=resume_message),
            response_source="none",
            state_interview=progress,
        )

    async def handle_dialog_action(self, payload: DialogActionRequest) -> DialogTurnResponse:
        context = await self._get_or_create_context(payload.session_id)
        card_id = normalize_card_id(payload.card_id)

        if card_id == "start_interview":
            return await self._ready_to_interview(context)

        selected_text = payload.question or payload.selected_text or payload.card_id
        return await self._handle_guidance_card(context, card_id, selected_text)

    async def handle_dialog_text(self, payload: DialogTextRequest) -> DialogTurnResponse:
        with perf_span("dialog.text.total", has_session=bool(payload.session_id), chars=len(payload.content)):
            context = await self._get_or_create_context(payload.session_id)
            if context.state == "end":
                progress = await self._get_or_create_interview_progress(context.session_id)
                return DialogTurnResponse(
                    session_id=context.session_id,
                    current_state=self._current_state(context),
                    previous_state=context.previous_state,
                    action="append_message",
                    message=DialogMessage(content="这次采访已经完成了，感谢您分享这些珍贵的人生故事。"),
                    response_source="none",
                    state_interview=progress,
                )
            if context.state == "READY_TO_INTERVIEW":
                await self._transition(context, "INTERVIEWING")
            elif context.state != "INTERVIEWING":
                await self._transition(context, "READY_TO_INTERVIEW")
                await self._transition(context, "INTERVIEWING")

            user_content = payload.content.strip()
            progress = await self._get_or_create_interview_progress(context.session_id)
            turn_stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
            await self._append_message(
                context.session_id,
                "user",
                user_content,
                stage_id=turn_stage_id,
            )
            history = await self._get_messages(context.session_id)
            stage_messages = self._stage_messages_by_id(history)
            stage_history = stage_messages.get(turn_stage_id) or await self._get_stage_messages(
                context.session_id,
                turn_stage_id,
            )

            graph_state = await self.interview_graph.run_turn(
                {
                    "session_id": context.session_id,
                    "interviewee_id": None,
                    "stage_id": turn_stage_id,
                    "completed": int(progress.get("completed", 0)),
                    "started_stage_id": progress.get("started_stage_id"),
                    "stage_flow": self._valid_stage_flow(progress.get("stage_flow")),
                    "stage_outcomes": self._valid_stage_outcomes(progress.get("stage_outcomes")),
                    "pending_stage_mentions": self._valid_stage_mentions(progress.get("pending_stage_mentions")),
                    "cross_stage_mentions": self._valid_cross_stage_mentions(progress.get("cross_stage_mentions")),
                    "cross_stage_current": self._valid_cross_stage_current(progress.get("cross_stage_current")),
                    "stage_transition_hint": str(progress.get("stage_transition_hint") or "")[:160],
                    "local_messages": stage_history,
                    "stage_messages": stage_messages,
                    "stage_seed": {
                        "stage_id": turn_stage_id,
                        "completed_main_question_ids": progress.get("completed_main_question_ids", []),
                        "active_main_question_id": progress.get("active_main_question_id"),
                        "awaiting_stage_completion": int(progress.get("awaiting_stage_completion", 0)),
                        "supplement_answered": int(progress.get("supplement_answered", 0)),
                    },
                    "global_messages": history,
                    "global_outline": {},
                    "user_message": user_content,
                }
            )
            if isinstance(graph_state.get("progress"), dict):
                graph_state = {**graph_state, **graph_state["progress"]}
            progress = self._hydrate_progress_view(graph_state)
            response_stage_id = str(graph_state.get("response_stage_id") or turn_stage_id)
            if response_stage_id not in INTERVIEW_STAGE_BY_ID:
                response_stage_id = turn_stage_id
            await self._assign_latest_user_message_stage(
                context.session_id,
                response_stage_id,
            )
            assistant_content = str(graph_state.get("assistant_message") or "")
            response_source = str(graph_state.get("response_source") or "llm")
            await self._append_message(
                context.session_id,
                "assistant",
                assistant_content,
                stage_id=response_stage_id,
            )
            await self._set_interview_progress(context.session_id, progress)
            progress = await self._interview_state_view(context.session_id, progress)
            context.updated_at = datetime.now(UTC)

        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=self._current_state(context),
            previous_state=context.previous_state,
            action="append_message",
            message=DialogMessage(content=assistant_content),
            response_source=response_source,
            state_interview=progress,
        )

    async def get_state(self, session_id: str) -> InterviewStateResponse:
        context = await self._get_or_create_context(session_id)
        return InterviewStateResponse(
            session_id=context.session_id,
            state=self._current_state(context),
            state_interview=await self._get_or_create_interview_progress(context.session_id),
        )

    async def get_userinfo(self, user_id: str) -> UserInfoResponse:
        return UserInfoResponse(
            user_id=user_id,
            userinfo=await self._get_userinfo(user_id),
        )

    async def save_userinfo(self, user_id: str, payload: UserInfoRequest) -> UserInfoResponse:
        mapping = {
            key: str(value).strip()
            for key, value in payload.model_dump().items()
            if str(key).strip() and str(value).strip()
        }
        await self._replace_userinfo(user_id, mapping)
        return UserInfoResponse(
            user_id=user_id,
            userinfo=await self._get_userinfo(user_id),
        )

    async def _ready_to_interview(self, context: InterviewContext) -> DialogTurnResponse:
        await self._transition(context, "READY_TO_INTERVIEW")
        await self._reset_interview_progress(context.session_id)
        progress = await self._get_or_create_interview_progress(context.session_id)
        icebreaker = await self.interview_agent.generate_icebreaker(
            recent_messages=await self._get_messages(context.session_id),
            stage_description=self._stage_description(progress),
        )
        message = icebreaker.reply
        await self._append_message(context.session_id, "assistant", message)
        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=self._current_state(context),
            previous_state=context.previous_state,
            action="ready_to_interview",
            message=DialogMessage(content=message),
            response_source=icebreaker.response_source,
            state_interview=progress,
        )

    async def _handle_guidance_card(
        self,
        context: InterviewContext,
        card_id: str,
        selected_text: str,
    ) -> DialogTurnResponse:
        generated = await self.guidance_llm.generate_guidance_response(
            card_id=card_id,
            selected_text=selected_text,
        )

        await self._transition(context, "GUIDANCE_CARD")
        context.updated_at = datetime.now(UTC)

        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=self._current_state(context),
            previous_state=context.previous_state,
            action="append_message",
            message=DialogMessage(content=generated["assistant_message"]),
            response_source=generated["response_source"],
        )

    async def _get_or_create_context(self, session_id: str | None = None) -> InterviewContext:
        if session_id:
            context = await self._get_context(session_id)
            if context is not None:
                return context
        return await self._create_context(session_id)

    async def _create_context(self, session_id: str | None = None) -> InterviewContext:
        now = datetime.now(UTC)
        context = InterviewContext(
            session_id=session_id or str(uuid4()),
            state="INIT",
            created_at=now,
            updated_at=now,
        )
        await self._save_state(context)
        return context

    async def _get_context(self, session_id: str) -> InterviewContext | None:
        raw = await self._redis_get(self._key(session_id))
        if raw is None:
            return None
        now = datetime.now(UTC)
        state = self._decode_state(raw)
        context = InterviewContext(
            session_id=session_id,
            state=state,
            created_at=now,
            updated_at=now,
        )
        if raw != state:
            await self._save_state(context)
        return context

    async def _save_state(self, context: InterviewContext) -> None:
        await self._overwrite_state_value(self._key(context.session_id), context.state)

    async def _redis_get(self, key: str) -> str | None:
        return await self.store.get(key)

    async def _redis_set(self, key: str, value: str) -> None:
        await self.store.set(key, value)

    async def _redis_hset(self, key: str, mapping: dict[str, str]) -> None:
        await self.store.hset(key, mapping)

    async def _redis_hgetall(self, key: str) -> dict[str, str]:
        return await self.store.hgetall(key)

    async def _redis_rpush(self, key: str, value: str) -> None:
        await self.store.rpush(key, value)

    async def _overwrite_state_value(self, key: str, value: str) -> None:
        """State-machine keys are scalar snapshots, never append-only history."""
        await self.store.overwrite_value(key, value)

    async def _redis_lrange(self, key: str, start: int, end: int) -> list[str]:
        return await self.store.lrange(key, start, end)

    async def _redis_delete(self, key: str) -> None:
        await self.store.delete(key)

    async def _reset_interview_progress(self, session_id: str) -> None:
        await self._redis_delete(self._interview_progress_key(session_id))
        await self._redis_delete(self._messages_key(session_id))
        await self.interview_agent.delete_checkpoint_thread(session_id)
        await self.interview_graph.delete_checkpoint_thread(session_id)
        await self._set_interview_progress(
            session_id,
            {
                "stage_id": FIRST_INTERVIEW_STAGE,
                "completed": 0,
                "pending_stage_mentions": {},
                "cross_stage_mentions": [],
                "cross_stage_current": None,
                "started_stage_id": None,
                "stage_flow": [],
                "stage_outcomes": {},
            },
        )

    async def _get_or_create_interview_progress(self, session_id: str) -> dict[str, Any]:
        checkpoint_getter = getattr(self.interview_graph, "get_checkpointed_state", None)
        if callable(checkpoint_getter):
            checkpoint_progress = await checkpoint_getter(session_id)
            if checkpoint_progress:
                return await self._interview_state_view(session_id, checkpoint_progress)

        raw = await self._redis_get(self._interview_progress_key(session_id))
        if not raw:
            progress = {
                "stage_id": FIRST_INTERVIEW_STAGE,
                "completed": 0,
                "pending_stage_mentions": {},
                "cross_stage_mentions": [],
                "cross_stage_current": None,
                "started_stage_id": None,
                "stage_flow": [],
                "stage_outcomes": {},
            }
            await self._set_interview_progress(session_id, progress)
            return await self._interview_state_view(session_id, progress)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        stage_id = data.get("stage_id") if data.get("stage_id") in INTERVIEW_STAGE_BY_ID else FIRST_INTERVIEW_STAGE
        completed = 1 if str(data.get("completed")) == "1" else 0
        completed_stage_ids = self._valid_stage_id_list(
            data.get("completed_stage_ids") or data.get("visited_stage_ids")
        )
        pending_stage_ids = self._valid_stage_id_list(data.get("pending_stage_ids"))
        pending_stage_mentions = self._valid_stage_mentions(data.get("pending_stage_mentions"))
        cross_stage_mentions = self._valid_cross_stage_mentions(data.get("cross_stage_mentions"))
        cross_stage_current = self._valid_cross_stage_current(data.get("cross_stage_current"))
        awaiting_stage_completion = 1 if str(data.get("awaiting_stage_completion")) == "1" else 0
        stage_transition_hint = str(data.get("stage_transition_hint") or "")[:160]
        completed_main_question_ids = self._valid_main_question_ids(data.get("completed_main_question_ids"))
        active_main_question_id = self._valid_main_question_id(data.get("active_main_question_id"))
        supplement_answered = 1 if str(data.get("supplement_answered")) == "1" else 0
        started_stage_id = data.get("started_stage_id") if data.get("started_stage_id") in INTERVIEW_STAGE_BY_ID else None
        stage_flow = self._valid_stage_flow(data.get("stage_flow"))
        stage_outcomes = self._valid_stage_outcomes(data.get("stage_outcomes"))
        legacy_statuses = self._valid_stage_statuses(
            data.get("stage_statuses"),
            stage_id,
            completed_stage_ids,
            pending_stage_ids,
        )
        completed_stage_ids = self._merge_stage_id_lists(
            completed_stage_ids,
            self._completed_stage_ids(legacy_statuses),
            self._completed_stage_ids_from_flow(stage_flow),
        )
        pending_stage_ids = [
            stage_id
            for stage_id in self._merge_stage_id_lists(
                pending_stage_ids,
                [stage_id for stage_id in INTERVIEW_STAGE_IDS if legacy_statuses.get(stage_id) == "pending"],
            )
            if stage_id not in completed_stage_ids
        ]
        if not completed:
            awaiting_stage_completion = 1 if self._remaining_main_question_count({
                "completed_main_question_ids": completed_main_question_ids
            }) == 0 else 0
        progress = self._hydrate_progress_view({
            "stage_id": stage_id,
            "completed": completed,
            "completed_stage_ids": completed_stage_ids,
            "pending_stage_ids": pending_stage_ids,
            "pending_stage_mentions": pending_stage_mentions,
            "cross_stage_mentions": cross_stage_mentions,
            "cross_stage_current": cross_stage_current,
            "stage_transition_hint": stage_transition_hint,
            "awaiting_stage_completion": awaiting_stage_completion,
            "completed_main_question_ids": completed_main_question_ids,
            "active_main_question_id": active_main_question_id,
            "supplement_answered": supplement_answered,
            "started_stage_id": started_stage_id,
            "stage_flow": stage_flow,
            "stage_outcomes": stage_outcomes,
        })
        await self._set_interview_progress(session_id, progress)
        return await self._interview_state_view(session_id, progress)

    async def _set_interview_progress(self, session_id: str, progress: dict[str, Any]) -> None:
        stage_id = str(progress.get("stage_id") or progress.get("current_stage") or FIRST_INTERVIEW_STAGE)
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            stage_id = FIRST_INTERVIEW_STAGE
        await self._overwrite_state_value(
            self._interview_progress_key(session_id),
            json.dumps(
                {
                    "stage_id": stage_id,
                    "completed": int(progress.get("completed", 0)),
                    "pending_stage_mentions": self._valid_stage_mentions(progress.get("pending_stage_mentions")),
                    "cross_stage_mentions": self._valid_cross_stage_mentions(progress.get("cross_stage_mentions")),
                    "cross_stage_current": self._valid_cross_stage_current(progress.get("cross_stage_current")),
                    "stage_transition_hint": str(progress.get("stage_transition_hint", ""))[:160],
                    "started_stage_id": progress.get("started_stage_id")
                    if progress.get("started_stage_id") in INTERVIEW_STAGE_BY_ID
                    else None,
                    "stage_flow": self._valid_stage_flow(progress.get("stage_flow")),
                    "stage_outcomes": self._valid_stage_outcomes(progress.get("stage_outcomes")),
                },
                ensure_ascii=False,
            ),
        )

    async def _interview_state_view(self, session_id: str, progress: dict[str, Any]) -> dict[str, Any]:
        view = self._hydrate_progress_view(progress)
        stage_id = str(view.get("stage_id") or FIRST_INTERVIEW_STAGE)
        child_state_getter = getattr(self.interview_graph, "get_stage_state", None)
        if not callable(child_state_getter):
            return view
        child_state = await child_state_getter(session_id, stage_id)
        if not isinstance(child_state, dict) or not child_state:
            return view
        return self._merge_child_state_view(view, child_state)

    @staticmethod
    def _merge_child_state_view(progress: dict[str, Any], child_state: dict[str, Any]) -> dict[str, Any]:
        stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
        completed_ids = InterviewStateMachine._valid_main_question_ids_for_stage(
            child_state.get("completed_main_question_ids"),
            stage_id,
        )
        active_question_id = InterviewStateMachine._valid_main_question_id_for_stage(
            child_state.get("active_main_question_id"),
            stage_id,
        )
        updated = {
            **progress,
            "completed_main_question_ids": completed_ids,
            "active_main_question_id": active_question_id,
            "awaiting_stage_completion": int(child_state.get("awaiting_stage_completion", 0)),
            "supplement_answered": int(child_state.get("supplement_answered", 0)),
        }
        flow = InterviewStateMachine._valid_stage_flow(updated.get("stage_flow"))
        flow = [
            {
                **item,
                **({"completed_main_question_ids": completed_ids} if item.get("stage_id") == stage_id and completed_ids else {}),
            }
            for item in flow
        ]
        return {**updated, "stage_flow": flow}

    async def _advance_interview_progress(
        self,
        context: InterviewContext,
        progress: dict[str, Any],
        *,
        round_decrement: int = 0,
    ) -> dict[str, Any]:
        if not progress.get("completed"):
            progress = self._sync_main_question_progress(progress)
            progress = self._sync_stage_flow(progress)
        await self._set_interview_progress(context.session_id, progress)
        return self._hydrate_progress_view(progress)

    async def _complete_awaiting_stage_if_needed(
        self,
        context: InterviewContext,
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        progress = self._sync_main_question_progress(progress)
        if progress.get("awaiting_stage_completion") and progress.get("supplement_answered"):
            current_stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
            progress = self._mark_stage_visited(progress, current_stage_id)
            progress = self._sync_stage_flow(progress, event="complete", event_stage_id=current_stage_id)
            next_stage_id = self._next_unvisited_stage_id(progress)
            if next_stage_id:
                transition_hint = self._stage_transition_hint_for(progress, next_stage_id)
                pending_stage_ids = [
                    stage_id
                    for stage_id in self._valid_stage_id_list(progress.get("pending_stage_ids"))
                    if stage_id != next_stage_id
                ]
                progress = {
                    **self._without_removed_progress_fields(progress),
                    "stage_id": next_stage_id,
                    "completed": 0,
                    "pending_stage_ids": pending_stage_ids,
                    "cross_stage_mentions": self._mark_cross_stage_mentions_used(
                        progress.get("cross_stage_mentions"),
                        next_stage_id,
                    ),
                    "cross_stage_current": None,
                    "stage_transition_hint": transition_hint,
                    "awaiting_stage_completion": 0,
                    "completed_main_question_ids": [],
                    "active_main_question_id": None,
                    "supplement_answered": 0,
                    "stage_flow": self._stage_flow_without_active(progress.get("stage_flow")),
                }
                progress = self._sync_stage_flow(progress)
            else:
                progress = {
                    **self._without_removed_progress_fields(progress),
                    "completed": 1,
                    "awaiting_stage_completion": 0,
                    "active_main_question_id": None,
                    "supplement_answered": 0,
                }
                progress = self._sync_stage_flow(progress, event="complete", event_stage_id=current_stage_id)
        progress = self._sync_stage_flow(progress)
        await self._set_interview_progress(context.session_id, progress)
        return self._hydrate_progress_view(progress)

    @staticmethod
    def _apply_initial_detected_stage(
        progress: dict[str, Any],
        stage_detection: Any,
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        has_prior_user_message = any(message.get("role") == "user" for message in history)
        if has_prior_user_message:
            return progress
        detected_stage = str(getattr(stage_detection, "stage_code", "unclear"))
        if detected_stage not in INTERVIEW_STAGE_BY_ID:
            return InterviewStateMachine._sync_stage_flow(progress, event="start")
        return InterviewStateMachine._move_progress_to_initial_stage(progress, detected_stage)

    @staticmethod
    def _apply_detected_stage_mention(
        progress: dict[str, Any],
        stage_detection: Any,
        user_content: str = "",
    ) -> dict[str, Any]:
        detected_stage = str(getattr(stage_detection, "stage_code", "unclear"))
        current_stage = str(progress.get("stage_id", ""))
        if detected_stage not in INTERVIEW_STAGE_BY_ID or detected_stage == current_stage:
            return progress
        completed_stage_ids = InterviewStateMachine._completed_stage_id_list(progress)
        pending = InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids"))
        mentions = InterviewStateMachine._valid_stage_mentions(progress.get("pending_stage_mentions"))
        if (
            detected_stage in completed_stage_ids
            or detected_stage in pending
        ):
            cross_stage_current = InterviewStateMachine._build_cross_stage_current(
                progress,
                detected_stage,
                user_content,
            )
            return {
                **InterviewStateMachine._without_removed_progress_fields(progress),
                "cross_stage_mentions": InterviewStateMachine._append_cross_stage_mention(
                    progress.get("cross_stage_mentions"),
                    cross_stage_current,
                ),
                "cross_stage_current": cross_stage_current,
            }
        mention = user_content.strip()[:120]
        if mention:
            mentions[detected_stage] = mention
        cross_stage_current = InterviewStateMachine._build_cross_stage_current(progress, detected_stage, user_content)
        cross_stage_mentions = InterviewStateMachine._append_cross_stage_mention(
            progress.get("cross_stage_mentions"),
            cross_stage_current,
        )
        return {
            **InterviewStateMachine._without_removed_progress_fields(progress),
            "completed_stage_ids": completed_stage_ids,
            "pending_stage_ids": [*pending, detected_stage],
            "pending_stage_mentions": mentions,
            "cross_stage_mentions": cross_stage_mentions,
            "cross_stage_current": cross_stage_current,
        }

    @staticmethod
    def _valid_stage_route(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"route": "normal_answer"}
        route_name = str(value.get("route") or "normal_answer")
        valid_routes = {
            "normal_answer",
            "extended_probe",
            "low_information",
            "off_stage_reference",
            "stage_complete",
            "emotional_blocked",
        }
        requested_stage_jump = value.get("requested_stage_jump")
        return {
            **value,
            "route": route_name if route_name in valid_routes else "normal_answer",
            "requested_stage_jump": requested_stage_jump if requested_stage_jump in INTERVIEW_STAGE_BY_ID else None,
        }

    @staticmethod
    def _apply_stage_route_jump(
        progress: dict[str, Any],
        stage_route: dict[str, Any],
        history: list[dict[str, str]],
        user_content: str,
    ) -> dict[str, Any]:
        if stage_route.get("route") != "off_stage_reference":
            return progress
        requested_stage_jump = stage_route.get("requested_stage_jump")
        if requested_stage_jump not in INTERVIEW_STAGE_BY_ID:
            return progress
        detection = InterviewStageDetectionResult(stage_code=str(requested_stage_jump))
        progress = InterviewStateMachine._apply_initial_detected_stage(progress, detection, history)
        return InterviewStateMachine._apply_detected_stage_mention(progress, detection, user_content)

    @staticmethod
    def _build_cross_stage_current(
        progress: dict[str, Any],
        detected_stage: str,
        user_content: str,
    ) -> dict[str, Any] | None:
        current_stage = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
        if detected_stage not in INTERVIEW_STAGE_BY_ID or detected_stage == current_stage:
            return None
        mention = user_content.strip()
        if not mention:
            return None
        return {
            "stage_id": detected_stage,
            "source_stage_id": current_stage,
            "mention": mention[:160],
            "created_at": datetime.now(UTC).isoformat(),
            "used": False,
        }

    @staticmethod
    def _append_cross_stage_mention(value: Any, mention: dict[str, Any] | None) -> list[dict[str, Any]]:
        mentions = InterviewStateMachine._valid_cross_stage_mentions(value)
        current = InterviewStateMachine._valid_cross_stage_current(mention)
        if current is None:
            return mentions
        duplicate = any(
            item.get("stage_id") == current.get("stage_id")
            and item.get("source_stage_id") == current.get("source_stage_id")
            and item.get("mention") == current.get("mention")
            for item in mentions
        )
        if duplicate:
            return mentions
        return [*mentions, current]

    @staticmethod
    def _clear_cross_stage_current(progress: dict[str, Any]) -> dict[str, Any]:
        return {**InterviewStateMachine._without_removed_progress_fields(progress), "cross_stage_current": None}

    @staticmethod
    def _move_progress_to_initial_stage(progress: dict[str, Any], detected_stage: str) -> dict[str, Any]:
        if detected_stage not in INTERVIEW_STAGE_BY_ID:
            return progress
        updated = {
            **InterviewStateMachine._without_removed_progress_fields(progress),
            "stage_id": detected_stage,
            "completed": 0,
            "stage_transition_hint": "",
            "awaiting_stage_completion": 0,
            "completed_main_question_ids": [],
            "active_main_question_id": None,
            "supplement_answered": 0,
            "stage_flow": InterviewStateMachine._stage_flow_without_active(progress.get("stage_flow")),
        }
        return InterviewStateMachine._sync_stage_flow(updated, event="start")

    @staticmethod
    def _mark_stage_visited(progress: dict[str, Any], stage_id: str) -> dict[str, Any]:
        completed_stage_ids = InterviewStateMachine._completed_stage_id_list(progress)
        if stage_id in INTERVIEW_STAGE_BY_ID and stage_id not in completed_stage_ids:
            completed_stage_ids = [*completed_stage_ids, stage_id]
        pending = [
            pending_stage
            for pending_stage in InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids"))
            if pending_stage != stage_id
        ]
        mentions = InterviewStateMachine._valid_stage_mentions(progress.get("pending_stage_mentions"))
        mentions.pop(stage_id, None)
        return {
            **InterviewStateMachine._without_removed_progress_fields(progress),
            "completed_stage_ids": completed_stage_ids,
            "pending_stage_ids": pending,
            "pending_stage_mentions": mentions,
        }

    @staticmethod
    def _next_unvisited_stage_id(progress: dict[str, Any]) -> str | None:
        visited = set(InterviewStateMachine._completed_stage_id_list(progress))
        pending = InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids"))
        for stage_id in pending:
            if stage_id not in visited:
                return stage_id
        for stage_id in INTERVIEW_STAGE_IDS:
            if stage_id not in visited:
                return stage_id
        return None

    @staticmethod
    def _stage_transition_hint_for(progress: dict[str, Any], next_stage_id: str) -> str:
        mentions = InterviewStateMachine._valid_stage_mentions(progress.get("pending_stage_mentions"))
        mention = mentions.pop(next_stage_id, "")
        progress["pending_stage_mentions"] = mentions
        stage = INTERVIEW_STAGE_BY_ID.get(next_stage_id, {})
        stage_name = str(stage.get("name", next_stage_id))
        completed_stage_ids = InterviewStateMachine._completed_stage_id_list(progress)
        stage_outcomes = InterviewStateMachine._valid_stage_outcomes(progress.get("stage_outcomes"))
        previous_stage_id = completed_stage_ids[-1] if completed_stage_ids else ""
        bridge_hint = stage_outcomes.get(previous_stage_id, {}).get("bridge_hint") if previous_stage_id else ""
        if bridge_hint and not mention:
            return f"上一阶段已完成，阶段总结给出的衔接提示：{bridge_hint}；现在进入{stage_name}，请柔和开启新阶段主问题。"
        if not mention:
            return f"上一阶段已完成，代码状态机按计划进入{stage_name}；请柔和开启新阶段主问题。"
        return f"用户上一阶段曾提到与{stage_name}相关的内容：{mention}"

    @staticmethod
    def _set_turn_transition_hint(
        progress: dict[str, Any],
        *,
        route_name: str | None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        progress = InterviewStateMachine._without_removed_progress_fields(progress)
        stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
        stage_name = InterviewStateMachine._stage_name(stage_id) or stage_id
        has_prior_user_message = any(message.get("role") == "user" for message in history or [])
        existing_hint = str(progress.get("stage_transition_hint") or "").strip()
        has_stage_switch_hint = existing_hint.startswith("用户上一阶段曾提到") or existing_hint.startswith("上一阶段已完成")

        if not has_prior_user_message:
            started_stage_id = progress.get("started_stage_id")
            route_text = {
                "normal_interview": "本轮路由为主问题推进",
                "extended_interview": "本轮路由为扩展追问",
                "emotional_guidance": "本轮路由已归一化为主问题推进",
            }.get(route_name or "", "正式采访即将开始")
            if started_stage_id == stage_id:
                hint = f"这是正式采访开始，用户第一段回答指向{stage_name}，{route_text}；请先自然接住，再按当前阶段推进。"
            else:
                hint = f"这是正式采访开始，代码状态机当前从{stage_name}阶段启动，{route_text}；请自然承接用户第一段回答。"
        elif route_name is None and has_stage_switch_hint:
            hint = existing_hint
        elif route_name == "extended_interview":
            prefix = f"当前进入{stage_name}阶段，{existing_hint}；" if has_stage_switch_hint else f"当前仍在{stage_name}阶段，"
            hint = f"{prefix}本轮路由为扩展追问；请承接用户刚提供的素材，只做一次单步追问。"
        elif route_name == "normal_interview":
            prefix = f"当前进入{stage_name}阶段，{existing_hint}；" if has_stage_switch_hint else f"当前仍在{stage_name}阶段，"
            hint = f"{prefix}本轮路由为主问题推进；请承接用户上一轮回答并继续当前阶段任务。"
        else:
            hint = f"当前处于{stage_name}阶段，代码状态机未触发阶段跳转；请承接用户回答并保持在当前阶段。"

        return {**progress, "stage_transition_hint": hint[:160]}

    @staticmethod
    def _valid_stage_id_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            stage_id = str(item)
            if stage_id in INTERVIEW_STAGE_BY_ID and stage_id not in result:
                result.append(stage_id)
        return result

    @staticmethod
    def _valid_stage_mentions(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, str] = {}
        for key, mention in value.items():
            stage_id = str(key)
            if stage_id in INTERVIEW_STAGE_BY_ID and isinstance(mention, str) and mention.strip():
                result[stage_id] = mention.strip()[:160]
        return result

    @staticmethod
    def _valid_stage_outcomes(value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for key, raw_outcome in value.items():
            stage_id = str(key)
            if stage_id not in INTERVIEW_STAGE_BY_ID or not isinstance(raw_outcome, dict):
                continue
            result[stage_id] = {
                "stage_id": stage_id,
                "summary": str(raw_outcome.get("summary") or "").strip()[:240],
                "key_events": InterviewStateMachine._clean_string_list(raw_outcome.get("key_events")),
                "key_people": InterviewStateMachine._clean_string_list(raw_outcome.get("key_people")),
                "emotional_notes": InterviewStateMachine._clean_string_list(raw_outcome.get("emotional_notes")),
                "unresolved_threads": InterviewStateMachine._clean_string_list(raw_outcome.get("unresolved_threads")),
                "bridge_hint": str(raw_outcome.get("bridge_hint") or "").strip()[:160],
            }
        return result

    @staticmethod
    def _clean_string_list(value: Any, *, limit: int = 8) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip()[:120] for item in value if str(item).strip()][:limit]

    @staticmethod
    def _valid_cross_stage_current(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        stage_id = str(value.get("stage_id") or "")
        source_stage_id = str(value.get("source_stage_id") or "")
        mention = str(value.get("mention") or "").strip()
        if stage_id not in INTERVIEW_STAGE_BY_ID or source_stage_id not in INTERVIEW_STAGE_BY_ID or not mention:
            return None
        return {
            "stage_id": stage_id,
            "source_stage_id": source_stage_id,
            "mention": mention[:160],
            "created_at": str(value.get("created_at") or "").strip()[:40],
            "used": bool(value.get("used", False)),
        }

    @staticmethod
    def _valid_cross_stage_mentions(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            mention = InterviewStateMachine._valid_cross_stage_current(item)
            if mention is not None:
                result.append(mention)
        return result[-20:]

    @staticmethod
    def _mark_cross_stage_mentions_used(value: Any, stage_id: str) -> list[dict[str, Any]]:
        mentions = InterviewStateMachine._valid_cross_stage_mentions(value)
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            return mentions
        return [
            {**mention, "used": True} if mention.get("stage_id") == stage_id else mention
            for mention in mentions
        ]

    @staticmethod
    def _valid_stage_statuses(
        value: Any,
        current_stage_id: str,
        completed_stage_ids: list[str],
        pending_stage_ids: list[str],
    ) -> dict[str, str]:
        statuses: dict[str, str] = {stage_id: "not_started" for stage_id in INTERVIEW_STAGE_IDS}
        if isinstance(value, dict):
            for key, raw_status in value.items():
                stage_id = str(key)
                status = str(raw_status)
                if stage_id in INTERVIEW_STAGE_BY_ID and status in STAGE_STATUS_VALUES:
                    statuses[stage_id] = status
        for stage_id in completed_stage_ids:
            statuses[stage_id] = "completed"
        for stage_id in pending_stage_ids:
            if statuses.get(stage_id) != "completed":
                statuses[stage_id] = "pending"
        for stage_id, status in list(statuses.items()):
            if status == "active" and stage_id != current_stage_id:
                statuses[stage_id] = "not_started"
        if current_stage_id in INTERVIEW_STAGE_BY_ID:
            if statuses.get(current_stage_id) != "completed":
                statuses[current_stage_id] = "active"
            if current_stage_id in pending_stage_ids:
                statuses[current_stage_id] = "active"
        return statuses

    @staticmethod
    def _valid_stage_flow(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            stage_id = str(item.get("stage_id") or "")
            if stage_id not in INTERVIEW_STAGE_BY_ID:
                continue
            status = str(item.get("status") or "active")
            if status not in STAGE_STATUS_VALUES:
                status = "active"
            entry: dict[str, Any] = {
                "stage_id": stage_id,
                "status": status,
            }
            started_by = str(item.get("started_by") or "").strip()
            if started_by:
                entry["started_by"] = started_by[:40]
            completed_ids = InterviewStateMachine._valid_main_question_ids(item.get("completed_main_question_ids"))
            if completed_ids:
                entry["completed_main_question_ids"] = completed_ids
            entered_at = str(item.get("entered_at") or "").strip()
            if entered_at:
                entry["entered_at"] = entered_at
            completed_at = str(item.get("completed_at") or "").strip()
            if completed_at:
                entry["completed_at"] = completed_at
            result.append(entry)
        return result

    @staticmethod
    def _stage_flow_without_active(value: Any) -> list[dict[str, Any]]:
        return [
            item
            for item in InterviewStateMachine._valid_stage_flow(value)
            if item.get("status") != "active"
        ]

    @staticmethod
    def _without_removed_progress_fields(progress: dict[str, Any]) -> dict[str, Any]:
        cleaned = {key: value for key, value in progress.items() if key not in REMOVED_PROGRESS_FIELDS}
        if "completed_stage_ids" not in cleaned and "visited_stage_ids" in progress:
            cleaned["completed_stage_ids"] = InterviewStateMachine._valid_stage_id_list(
                progress.get("visited_stage_ids")
            )
        return cleaned

    @staticmethod
    def _hydrate_progress_view(progress: dict[str, Any]) -> dict[str, Any]:
        progress = InterviewStateMachine._sync_stage_flow(progress)
        stage_id = str(progress.get("stage_id") or progress.get("current_stage") or FIRST_INTERVIEW_STAGE)
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            stage_id = FIRST_INTERVIEW_STAGE
        completed_stage_ids = InterviewStateMachine._completed_stage_id_list(progress)
        pending = InterviewStateMachine._pending_stage_id_list(progress)
        started_stage_id = progress.get("started_stage_id")
        return {
            "stage_id": stage_id,
            "completed": int(progress.get("completed", 0)),
            "completed_stage_ids": completed_stage_ids,
            "pending_stage_ids": pending,
            "pending_stage_mentions": InterviewStateMachine._valid_stage_mentions(progress.get("pending_stage_mentions")),
            "cross_stage_mentions": InterviewStateMachine._valid_cross_stage_mentions(
                progress.get("cross_stage_mentions")
            ),
            "cross_stage_current": InterviewStateMachine._valid_cross_stage_current(
                progress.get("cross_stage_current")
            ),
            "stage_transition_hint": str(progress.get("stage_transition_hint") or "")[:160],
            "awaiting_stage_completion": int(progress.get("awaiting_stage_completion", 0)),
            "completed_main_question_ids": InterviewStateMachine._valid_main_question_ids(
                progress.get("completed_main_question_ids")
            ),
            "active_main_question_id": InterviewStateMachine._valid_main_question_id(
                progress.get("active_main_question_id")
            ),
            "supplement_answered": int(progress.get("supplement_answered", 0)),
            "started_stage_id": started_stage_id if started_stage_id in INTERVIEW_STAGE_BY_ID else None,
            "stage_flow": InterviewStateMachine._valid_stage_flow(progress.get("stage_flow")),
            "stage_outcomes": InterviewStateMachine._valid_stage_outcomes(progress.get("stage_outcomes")),
        }

    @staticmethod
    def _sync_stage_flow(
        progress: dict[str, Any],
        *,
        event: str = "enter",
        event_stage_id: str | None = None,
    ) -> dict[str, Any]:
        current_stage_id = str(progress.get("stage_id") or progress.get("current_stage") or FIRST_INTERVIEW_STAGE)
        completed_stage_ids = InterviewStateMachine._completed_stage_id_list(progress)
        pending = InterviewStateMachine._pending_stage_id_list(progress)
        flow = InterviewStateMachine._valid_stage_flow(progress.get("stage_flow"))
        started_stage_id = progress.get("started_stage_id")
        if started_stage_id not in INTERVIEW_STAGE_BY_ID:
            started_stage_id = current_stage_id if current_stage_id in INTERVIEW_STAGE_BY_ID else None

        flow = [
            item
            for item in flow
            if not (
                (item.get("status") == "active" and item.get("stage_id") != current_stage_id)
                or (item.get("status") == "pending" and item.get("stage_id") not in pending)
            )
        ]
        for completed_stage_id in completed_stage_ids:
            flow = InterviewStateMachine._upsert_stage_flow_entry(
                flow,
                completed_stage_id,
                "completed",
                progress,
            )
        for pending_stage_id in pending:
            if pending_stage_id not in completed_stage_ids and pending_stage_id != current_stage_id:
                flow = InterviewStateMachine._upsert_stage_flow_entry(
                    flow,
                    pending_stage_id,
                    "pending",
                    progress,
                )

        target_stage_id = event_stage_id or current_stage_id
        if event == "complete" and target_stage_id in INTERVIEW_STAGE_BY_ID:
            completed_stage_ids = InterviewStateMachine._merge_stage_id_lists(completed_stage_ids, [target_stage_id])
            flow = InterviewStateMachine._upsert_stage_flow_entry(
                flow,
                target_stage_id,
                "completed",
                progress,
            )
        just_completed_current_stage = event == "complete" and target_stage_id == current_stage_id
        if current_stage_id in INTERVIEW_STAGE_BY_ID and not progress.get("completed") and not just_completed_current_stage:
            flow = InterviewStateMachine._upsert_stage_flow_entry(
                flow,
                current_stage_id,
                "active",
                progress,
                started_by="initial" if event == "start" else "state_machine",
            )
        return {
            **InterviewStateMachine._without_removed_progress_fields(progress),
            "started_stage_id": started_stage_id,
            "completed_stage_ids": completed_stage_ids,
            "stage_flow": flow,
        }

    @staticmethod
    def _upsert_stage_flow_entry(
        flow: list[dict[str, Any]],
        stage_id: str,
        status: str,
        progress: dict[str, Any],
        *,
        started_by: str | None = None,
    ) -> list[dict[str, Any]]:
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            return flow
        existing_index = next((index for index, item in enumerate(flow) if item.get("stage_id") == stage_id), None)
        entry = {
            "stage_id": stage_id,
            "status": status,
        }
        if started_by:
            entry["started_by"] = started_by
        if existing_index is None:
            entry["entered_at"] = datetime.now(UTC).isoformat()
        else:
            existing = flow[existing_index]
            if existing.get("entered_at"):
                entry["entered_at"] = existing["entered_at"]
            if existing.get("started_by") and not started_by:
                entry["started_by"] = existing["started_by"]
            if existing.get("completed_main_question_ids") and stage_id != str(
                progress.get("stage_id") or progress.get("current_stage") or ""
            ):
                entry["completed_main_question_ids"] = existing["completed_main_question_ids"]
        if stage_id == str(progress.get("stage_id") or progress.get("current_stage") or ""):
            completed_ids = InterviewStateMachine._valid_main_question_ids(progress.get("completed_main_question_ids"))
            if completed_ids:
                entry["completed_main_question_ids"] = completed_ids
        if status == "completed":
            existing_completed_at = (
                flow[existing_index].get("completed_at")
                if existing_index is not None and isinstance(flow[existing_index], dict)
                else None
            )
            entry["completed_at"] = existing_completed_at or datetime.now(UTC).isoformat()
        if existing_index is None:
            return [*flow, entry]
        updated = [*flow]
        updated[existing_index] = {**updated[existing_index], **entry}
        return updated

    @staticmethod
    def _completed_stage_ids(stage_statuses: dict[str, str]) -> list[str]:
        return [stage_id for stage_id in INTERVIEW_STAGE_IDS if stage_statuses.get(stage_id) == "completed"]

    @staticmethod
    def _completed_stage_id_list(progress: dict[str, Any]) -> list[str]:
        legacy_statuses = InterviewStateMachine._valid_stage_statuses(
            progress.get("stage_statuses"),
            str(progress.get("stage_id") or progress.get("current_stage") or FIRST_INTERVIEW_STAGE),
            InterviewStateMachine._valid_stage_id_list(progress.get("completed_stage_ids")),
            InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids")),
        )
        return InterviewStateMachine._merge_stage_id_lists(
            InterviewStateMachine._valid_stage_id_list(progress.get("completed_stage_ids")),
            InterviewStateMachine._valid_stage_id_list(progress.get("visited_stage_ids")),
            InterviewStateMachine._completed_stage_ids_from_flow(progress.get("stage_flow")),
            InterviewStateMachine._completed_stage_ids(legacy_statuses),
        )

    @staticmethod
    def _pending_stage_id_list(progress: dict[str, Any]) -> list[str]:
        completed_stage_ids = set(InterviewStateMachine._completed_stage_id_list(progress))
        pending_from_flow = [
            item["stage_id"]
            for item in InterviewStateMachine._valid_stage_flow(progress.get("stage_flow"))
            if item.get("status") == "pending"
        ]
        pending_from_mentions = [
            stage_id
            for stage_id in InterviewStateMachine._valid_stage_mentions(
                progress.get("pending_stage_mentions")
            )
            if stage_id not in completed_stage_ids
        ]
        return [
            stage_id
            for stage_id in InterviewStateMachine._merge_stage_id_lists(
                InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids")),
                pending_from_flow,
                pending_from_mentions,
            )
            if stage_id not in completed_stage_ids
        ]

    @staticmethod
    def _completed_stage_ids_from_flow(value: Any) -> list[str]:
        return [
            item["stage_id"]
            for item in InterviewStateMachine._valid_stage_flow(value)
            if item.get("status") == "completed"
        ]

    @staticmethod
    def _merge_stage_id_lists(*values: list[str]) -> list[str]:
        merged: list[str] = []
        for stage_id in INTERVIEW_STAGE_IDS:
            if any(stage_id in value for value in values) and stage_id not in merged:
                merged.append(stage_id)
        return merged

    @staticmethod
    def _stage_name(stage_id: Any) -> str | None:
        return InterviewStageRuntime.stage_name(stage_id)

    @staticmethod
    def _valid_main_question_id(value: Any) -> int | None:
        return InterviewStateMachine._valid_main_question_id_for_stage(value)

    @staticmethod
    def _valid_main_question_id_for_stage(value: Any, stage_id: str | None = None) -> int | None:
        return InterviewStageRuntime.valid_main_question_id(value, stage_id)

    @staticmethod
    def _valid_main_question_ids(value: Any) -> list[int]:
        return InterviewStateMachine._valid_main_question_ids_for_stage(value)

    @staticmethod
    def _valid_main_question_ids_for_stage(value: Any, stage_id: str | None = None) -> list[int]:
        return InterviewStageRuntime.valid_main_question_ids(value, stage_id)

    @staticmethod
    def _main_question_ids_for_stage(stage_id: str | None) -> tuple[int, ...]:
        return InterviewStageRuntime.main_question_ids_for_stage(stage_id)

    @staticmethod
    def _sync_main_question_progress(progress: dict[str, Any]) -> dict[str, Any]:
        return InterviewStageRuntime.sync_main_question_progress(
            InterviewStateMachine._without_removed_progress_fields(progress)
        )

    @staticmethod
    def _remaining_main_question_count(progress: dict[str, Any]) -> int:
        return InterviewStageRuntime.remaining_main_question_count(progress)

    @staticmethod
    def _mark_active_main_question_answered(progress: dict[str, Any]) -> dict[str, Any]:
        return InterviewStageRuntime.mark_active_main_question_answered(
            InterviewStateMachine._without_removed_progress_fields(progress)
        )

    @staticmethod
    def _stage_main_questions_completed(progress: dict[str, Any]) -> bool:
        stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
        completed_ids = set(InterviewStageRuntime.valid_main_question_ids(progress.get("completed_main_question_ids"), stage_id))
        return set(InterviewStageRuntime.main_question_ids_for_stage(stage_id)).issubset(completed_ids)

    @staticmethod
    def _set_active_main_question(
        progress: dict[str, Any],
        route_name: str,
        main_question_id: Any,
    ) -> dict[str, Any]:
        return InterviewStageRuntime.set_active_main_question(
            InterviewStateMachine._without_removed_progress_fields(progress),
            route_name,
            main_question_id,
        )

    async def _append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        stage_id: str | None = None,
    ) -> None:
        message = {
            "role": role,
            "content": content,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if stage_id in INTERVIEW_STAGE_BY_ID:
            message["stage_id"] = stage_id
        await self._redis_rpush(self._messages_key(session_id), json.dumps(message, ensure_ascii=False))

    async def _get_messages(self, session_id: str) -> list[dict[str, str]]:
        raw_messages = await self._redis_lrange(self._messages_key(session_id), 0, -1)
        messages: list[dict[str, str]] = []
        for item in raw_messages:
            try:
                data = json.loads(item)
            except json.JSONDecodeError:
                continue
            role = data.get("role")
            content = data.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                message = {"role": role, "content": content}
                stage_id = data.get("stage_id")
                if stage_id in INTERVIEW_STAGE_BY_ID:
                    message["stage_id"] = stage_id
                messages.append(message)
        return messages

    async def _get_stage_messages(self, session_id: str, stage_id: str) -> list[dict[str, str]]:
        messages = await self._get_messages(session_id)
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            return messages
        scoped = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
            if message.get("stage_id") == stage_id
        ]
        if scoped:
            return scoped
        return [
            {"role": message["role"], "content": message["content"]}
            for message in messages
            if "stage_id" not in message
        ]

    @staticmethod
    def _stage_messages_by_id(messages: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = {}
        for message in messages:
            stage_id = message.get("stage_id")
            if stage_id not in INTERVIEW_STAGE_BY_ID:
                continue
            grouped.setdefault(stage_id, []).append(
                {"role": message["role"], "content": message["content"]}
            )
        return grouped

    @staticmethod
    def _build_resume_message(progress: dict[str, Any], messages: list[dict[str, str]]) -> str:
        stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
        stage_name = InterviewStateMachine._stage_name(stage_id) or stage_id
        last_assistant_message = InterviewStateMachine._last_message_content(messages, "assistant")
        active_question_id = InterviewStateMachine._valid_main_question_id_for_stage(
            progress.get("active_main_question_id"),
            stage_id,
        )
        question_text = f"上次我问到：{last_assistant_message}" if last_assistant_message else "我们可以接着上次的地方慢慢聊。"

        if int(progress.get("completed", 0)):
            return "欢迎回来，这次采访已经完成了。您可以回看刚才整理下来的内容，也可以之后再开启新的补充采访。"

        if active_question_id == SUPPLEMENT_QUESTION_ID or int(progress.get("awaiting_stage_completion", 0)):
            return f"欢迎回来。上次{stage_name}阶段的主要内容已经聊得比较完整了，{question_text}"

        if active_question_id is None:
            return f"欢迎回来，我们可以继续顺着上次那段经历慢慢说。{question_text}"

        transition_hint = str(progress.get("stage_transition_hint") or "")
        if "上一阶段" in transition_hint or "曾提到" in transition_hint:
            return f"欢迎回来。我们上次已经接到{stage_name}阶段了，可以顺着这个节奏继续。{question_text}"

        return f"欢迎回来，我们接着上次的节奏慢慢聊。{question_text}"

    @staticmethod
    def _last_message_content(messages: list[dict[str, str]], role: str) -> str:
        for message in reversed(messages):
            if message.get("role") == role and message.get("content"):
                return str(message["content"])
        return ""

    async def _assign_latest_user_message_stage(self, session_id: str, stage_id: str) -> None:
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            return
        raw_messages = await self._redis_lrange(self._messages_key(session_id), 0, -1)
        if not raw_messages:
            return
        decoded: list[dict[str, Any]] = []
        latest_user_index: int | None = None
        for index, item in enumerate(raw_messages):
            try:
                message = json.loads(item)
            except json.JSONDecodeError:
                decoded.append({})
                continue
            decoded.append(message if isinstance(message, dict) else {})
            if message.get("role") == "user":
                latest_user_index = index
        if latest_user_index is None:
            return
        decoded[latest_user_index]["stage_id"] = stage_id
        await self._redis_delete(self._messages_key(session_id))
        for message in decoded:
            if message:
                await self._redis_rpush(self._messages_key(session_id), json.dumps(message, ensure_ascii=False))

    @staticmethod
    def _stage_description(progress: dict[str, Any]) -> str:
        return InterviewStageRuntime.stage_description(progress)

    @staticmethod
    def _transition_hint_for_description(progress: dict[str, Any]) -> str:
        return InterviewStageRuntime.transition_hint(progress)

    @staticmethod
    def _cross_stage_instruction_for_description(progress: dict[str, Any]) -> str:
        return InterviewStageRuntime.cross_stage_instruction(progress)

    @staticmethod
    def _stage_task(stage_id: str, remaining_rounds: int) -> str:
        return InterviewStageRuntime.stage_task(stage_id, remaining_rounds)

    @staticmethod
    def _format_main_question_ids(question_ids: list[int]) -> str:
        return InterviewStageRuntime.format_main_question_ids(question_ids)

    @staticmethod
    def _next_stage_id(stage_id: str) -> str | None:
        return InterviewStageRuntime.next_stage_id(stage_id)

    async def _transition(self, context: InterviewContext, to_state: InterviewState) -> None:
        if context.state != to_state:
            context.previous_state = self._current_state(context)
            context.state = to_state
        context.updated_at = datetime.now(UTC)
        await self._save_state(context)

    async def _get_userinfo(self, user_id: str) -> dict[str, str]:
        return await self._redis_hgetall(self._userinfo_key(user_id))

    async def _replace_userinfo(self, user_id: str, mapping: dict[str, str]) -> None:
        key = self._userinfo_key(user_id)
        await self._redis_delete(key)
        if mapping:
            await self._redis_hset(key, mapping)

    @staticmethod
    def _decode_state(raw: str) -> str:
        if not raw.startswith("{"):
            return raw if raw in VALID_INTERVIEW_STATES else "INIT"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return "INIT"
        state = data.get("state") or data.get("current_state")
        return state if isinstance(state, str) and state in VALID_INTERVIEW_STATES else "INIT"

    @staticmethod
    def _current_state(context: InterviewContext) -> InterviewState:
        state = context.state if context.state in VALID_INTERVIEW_STATES else "INIT"
        return cast(InterviewState, state)

    @staticmethod
    def _key(session_id: str) -> str:
        return InterviewSessionStore.state_key(session_id)

    @staticmethod
    def _userinfo_key(user_id: str) -> str:
        return InterviewSessionStore.userinfo_key(user_id)

    @staticmethod
    def _interview_progress_key(session_id: str) -> str:
        return InterviewSessionStore.interview_progress_key(session_id)

    @staticmethod
    def _messages_key(session_id: str) -> str:
        return InterviewSessionStore.messages_key(session_id)
