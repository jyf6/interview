from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from langgraph.graph import END, StateGraph
from langgraph.types import Command

from app.data.interview_stage_config import FIRST_INTERVIEW_STAGE, INTERVIEW_STAGE_BY_ID
from app.graphs.interview_graph_state import ChildState, ParentState, StageEvent
from app.graphs.interview_stage_runtime import InterviewStageRuntime
from app.services.interview_agent_service import (
    InterviewAgentService,
    InterviewRouteResult,
    InterviewStageRouteResult,
)

NON_ANSWER_STAGE_ROUTES = {"low_information", "emotional_blocked"}


def stage_route_counts_as_answer(route_name: str | None) -> bool:
    return bool(route_name) and route_name not in NON_ANSWER_STAGE_ROUTES


class BaseInterviewStageSubgraph:
    """Base module for one interview stage.

    The parent interface is intentionally small: a stage node emits one
    StageEvent and lets the parent decide whether to stay, complete, or jump.
    """

    def __init__(
        self,
        agent: InterviewAgentService,
        *,
        stage_id: str | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.agent = agent
        self.stage_id = stage_id
        self.graph = self._build_graph(checkpointer=checkpointer)

    async def run(self, state: ChildState, *, session_id: str | None = None) -> ChildState:
        return await self.graph.ainvoke(state, self._graph_config(session_id, state.get("stage_id")))

    def as_parent_node(self) -> Callable[[ParentState], Awaitable[Command]]:
        async def run_stage(state: ParentState) -> Command:
            child_state = await self.run(
                self._child_input_from_parent(state),
                session_id=state.get("session_id"),
            )
            return Command(
                goto="advance_stage",
                update={
                    "stage_event": self._event_from_child(child_state),
                    "requested_stage_jump": child_state.get("requested_stage_jump"),
                },
            )

        return run_stage

    async def get_checkpointed_state(self, session_id: str, stage_id: str | None = None) -> dict[str, Any] | None:
        snapshot = await self.graph.aget_state(self._graph_config(session_id, stage_id or self.stage_id))
        return dict(snapshot.values) if isinstance(snapshot.values, dict) else None

    async def delete_checkpoint_thread(self, session_id: str) -> None:
        checkpointer = getattr(self.graph, "checkpointer", None)
        if checkpointer is None:
            return
        await checkpointer.adelete_thread(f"interview-stage:{session_id}:{self._configured_stage_id()}")

    def _build_graph(self, *, checkpointer: Any | None = None) -> Any:
        graph = StateGraph(ChildState)
        graph.add_node("route", self._route)
        graph.add_node("handoff_parent", self._handoff_parent)
        graph.add_node("low_information_reply", self._low_information_reply)
        graph.add_node("interview_reply", self._interview_reply)
        graph.add_node("summarize_stage", self._summarize_stage)
        graph.set_entry_point("route")
        graph.add_conditional_edges(
            "route",
            self._select_reply_node,
            {
                "handoff_parent": "handoff_parent",
                "low_information_reply": "low_information_reply",
                "interview_reply": "interview_reply",
                "summarize_stage": "summarize_stage",
            },
        )
        graph.add_edge("handoff_parent", END)
        graph.add_edge("low_information_reply", END)
        graph.add_conditional_edges(
            "interview_reply",
            self._select_after_interview_reply,
            {
                "summarize_stage": "summarize_stage",
                "end": END,
            },
        )
        graph.add_edge("summarize_stage", END)
        return graph.compile(checkpointer=checkpointer)

    def _graph_config(self, session_id: str | None, stage_id: str | None = None) -> dict[str, dict[str, str]]:
        thread_id = session_id or f"ephemeral:{uuid4()}"
        configured_stage_id = stage_id or self._configured_stage_id()
        return {"configurable": {"thread_id": f"interview-stage:{thread_id}:{configured_stage_id}"}}

    def _configured_stage_id(self) -> str:
        return self.stage_id if self.stage_id in INTERVIEW_STAGE_BY_ID else FIRST_INTERVIEW_STAGE

    def _child_input_from_parent(self, state: ParentState) -> ChildState:
        stage_id = self._configured_stage_id()
        stage_messages = state.get("stage_messages", {})
        local_messages = stage_messages.get(stage_id) if isinstance(stage_messages, dict) else None
        child_input: ChildState = {
            "session_id": state.get("session_id", ""),
            "stage_id": stage_id,
            "local_messages": local_messages or state.get("local_messages", []),
            "stage_outcomes": state.get("stage_outcomes", {}),
            "global_outline": state.get("global_outline", {}),
            "user_message": state["user_message"],
            "stage_transition_hint": state.get("stage_transition_hint", ""),
            "cross_stage_current": state.get("cross_stage_current"),
        }

        # Migration bridge only: old parent snapshots may still carry these
        # stage-local fields. New parent graph output never writes them back.
        seed = state.get("stage_seed", {})
        seed = seed if isinstance(seed, dict) else {}
        if str(seed.get("stage_id") or stage_id) == stage_id:
            for key in (
                "completed_main_question_ids",
                "active_main_question_id",
                "awaiting_stage_completion",
                "supplement_answered",
            ):
                if key in seed:
                    child_input[key] = seed[key]  # type: ignore[literal-required]
        return child_input

    @staticmethod
    def _event_from_child(state: ChildState) -> StageEvent:
        event = state.get("stage_event")
        if isinstance(event, dict) and event.get("type"):
            return event
        return BaseInterviewStageSubgraph._stage_event(state, "stay")

    async def _route(self, state: ChildState) -> ChildState:
        result = await self.agent.judge_stage_route(
            user_message=state["user_message"],
            local_messages=state.get("local_messages", []),
            stage_description=self._stage_description(state),
            remaining_rounds=self._remaining_rounds(state),
        )
        route_name = result.route
        turn_route = self._turn_route_for_stage_route(result)
        return {
            "stage_route": result.model_dump(mode="json"),
            "turn_route": turn_route.model_dump(mode="json"),
            "legacy_route_name": turn_route.route,
            "answer_counted": stage_route_counts_as_answer(route_name),
            "requested_stage_jump": result.requested_stage_jump,
            "missing_info": result.missing_info,
        }

    @staticmethod
    def _select_reply_node(state: ChildState) -> str:
        route_name = str(state.get("stage_route", {}).get("route") or "")
        requested_stage_jump = state.get("requested_stage_jump")
        if (
            route_name == "off_stage_reference"
            and requested_stage_jump in INTERVIEW_STAGE_BY_ID
            and requested_stage_jump != BaseInterviewStageSubgraph._stage_id(state)
        ):
            return "handoff_parent"
        if route_name in NON_ANSWER_STAGE_ROUTES:
            return "low_information_reply"
        if route_name == "stage_complete":
            return "summarize_stage"
        if state.get("answer_counted", True) and InterviewStageRuntime.answering_supplement(
            BaseInterviewStageSubgraph._stage_progress_from_state(state)
        ):
            return "summarize_stage"
        return "interview_reply"

    @staticmethod
    def _select_after_interview_reply(state: ChildState) -> str:
        return "summarize_stage" if state.get("stage_complete") else "end"

    async def _handoff_parent(self, state: ChildState) -> ChildState:
        return {
            "assistant_message": "",
            "response_source": "none",
            "main_question_id": None,
            "answer_counted": False,
            "stage_complete": False,
            "stage_event": self._stage_event(
                state,
                "jump",
                target_stage_id=state.get("requested_stage_jump"),
            ),
        }

    async def _low_information_reply(self, state: ChildState) -> ChildState:
        reply = await self.agent.generate_low_information_reply(
            user_message=state["user_message"],
            local_messages=state.get("local_messages", []),
            stage_description=self._stage_description(state),
        )
        update: ChildState = {
            "assistant_message": reply,
            "response_source": "llm",
            "main_question_id": None,
            "answer_counted": False,
            "stage_complete": False,
            "legacy_route_name": "normal_interview",
        }
        return {**update, "stage_event": self._stage_event({**state, **update}, "stay")}

    async def _interview_reply(self, state: ChildState) -> ChildState:
        turn_route = InterviewRouteResult.model_validate(state["turn_route"])
        completed_ids = self._completed_ids_for_reply(state)
        stage_description = self._stage_description(state)
        reply, response_source, main_question_id = await self.agent.generate_reply_for_route(
            route=turn_route,
            session_id=state.get("session_id"),
            interview_progress=self._stage_progress_from_state(state),
            user_message=state["user_message"],
            recent_messages=state.get("local_messages", []),
            stage_description=stage_description,
            remaining_rounds=self._remaining_rounds(state),
            completed_main_question_ids=completed_ids,
        )
        progress = InterviewStageRuntime.mark_active_main_question_answered(self._stage_progress_from_state(state))
        progress = InterviewStageRuntime.set_active_main_question(progress, turn_route.route, main_question_id)
        progress = InterviewStageRuntime.sync_main_question_progress(progress)
        update: ChildState = {
            **self._state_update_from_progress(progress),
            "assistant_message": reply,
            "response_source": response_source,
            "main_question_id": main_question_id,
            "legacy_route_name": turn_route.route,
            "answer_counted": True,
            "stage_complete": InterviewStageRuntime.should_finalize_stage(progress),
        }
        return {**update, "stage_event": self._stage_event({**state, **update}, "stay")}

    async def _summarize_stage(self, state: ChildState) -> ChildState:
        progress = self._stage_progress_from_state(state)
        if state.get("answer_counted", True):
            progress = InterviewStageRuntime.mark_active_main_question_answered(progress)
        progress = InterviewStageRuntime.sync_main_question_progress(progress)
        stage_id = InterviewStageRuntime.stage_id(progress)
        outcome = await self.agent.summarize_stage(
            stage_id=stage_id,
            stage_description=self._stage_description({**state, **self._state_update_from_progress(progress)}),
            local_messages=state.get("local_messages", []),
            global_outline=state.get("global_outline", {}),
        )
        update: ChildState = {
            **self._state_update_from_progress(progress),
            "stage_complete": True,
            "stage_outcome": outcome,
            "assistant_message": state.get("assistant_message")
            or "这一阶段的内容我先帮您收束住，接下来我们顺着时间往后聊。",
            "response_source": state.get("response_source", "llm"),
            "main_question_id": None,
            "answer_counted": bool(state.get("answer_counted", True)),
            "legacy_route_name": state.get("legacy_route_name", "normal_interview"),
        }
        return {**update, "stage_event": self._stage_event({**state, **update}, "complete")}

    @staticmethod
    def _turn_route_for_stage_route(stage_route: InterviewStageRouteResult) -> InterviewRouteResult:
        if stage_route.route == "extended_probe":
            return InterviewRouteResult(
                route="extended_interview",
                emotion_type="none",
                needs_emotional_support=False,
                confidence=stage_route.confidence,
                reason=stage_route.reason,
                round_decrement=0,
            )
        if stage_route.route == "emotional_blocked":
            return InterviewRouteResult(
                route="normal_interview",
                emotion_type="unclear",
                needs_emotional_support=True,
                confidence=stage_route.confidence,
                reason=stage_route.reason,
                should_change_topic=True,
                do_not_probe_current_topic=True,
                round_decrement=1,
            )
        return InterviewRouteResult(
            route="normal_interview",
            emotion_type="none",
            needs_emotional_support=False,
            confidence=stage_route.confidence,
            reason=stage_route.reason,
            round_decrement=1,
        )

    @staticmethod
    def _completed_ids_for_reply(state: ChildState) -> list[int]:
        progress = BaseInterviewStageSubgraph._stage_progress_from_state(state)
        stage_id = InterviewStageRuntime.stage_id(progress)
        completed_ids = InterviewStageRuntime.valid_main_question_ids(
            progress.get("completed_main_question_ids", state.get("completed_main_question_ids", [])),
            stage_id,
        )
        if not state.get("answer_counted", True):
            return completed_ids
        active_question_id = InterviewStageRuntime.valid_main_question_id(
            progress.get("active_main_question_id", state.get("active_main_question_id")),
            stage_id,
        )
        if active_question_id is not None and active_question_id != 9 and active_question_id not in completed_ids:
            completed_ids.append(active_question_id)
        return completed_ids

    @staticmethod
    def _stage_id(state: ChildState) -> str:
        stage_id = str(state.get("stage_id") or FIRST_INTERVIEW_STAGE)
        return stage_id if stage_id in INTERVIEW_STAGE_BY_ID else FIRST_INTERVIEW_STAGE

    @staticmethod
    def _stage_progress_from_state(state: ChildState) -> dict[str, Any]:
        stage_id = BaseInterviewStageSubgraph._stage_id(state)
        return InterviewStageRuntime.sync_main_question_progress(
            {
                "stage_id": stage_id,
                "completed": 0,
                "completed_main_question_ids": state.get("completed_main_question_ids", []),
                "active_main_question_id": state.get("active_main_question_id"),
                "awaiting_stage_completion": int(state.get("awaiting_stage_completion", 0)),
                "supplement_answered": int(state.get("supplement_answered", 0)),
                "stage_transition_hint": state.get("stage_transition_hint", ""),
                "cross_stage_current": state.get("cross_stage_current"),
            }
        )

    @staticmethod
    def _state_update_from_progress(progress: dict[str, Any]) -> ChildState:
        return {
            "stage_id": InterviewStageRuntime.stage_id(progress),
            "completed_main_question_ids": InterviewStageRuntime.valid_main_question_ids(
                progress.get("completed_main_question_ids"),
                InterviewStageRuntime.stage_id(progress),
            ),
            "active_main_question_id": InterviewStageRuntime.valid_main_question_id(
                progress.get("active_main_question_id"),
                InterviewStageRuntime.stage_id(progress),
            ),
            "awaiting_stage_completion": int(progress.get("awaiting_stage_completion", 0)),
            "supplement_answered": int(progress.get("supplement_answered", 0)),
        }

    @staticmethod
    def _stage_description(state: ChildState) -> str:
        explicit = str(state.get("stage_description") or "").strip()
        if explicit:
            return explicit
        return InterviewStageRuntime.stage_description(BaseInterviewStageSubgraph._stage_progress_from_state(state))

    @staticmethod
    def _remaining_rounds(state: ChildState) -> int:
        if "remaining_rounds" in state:
            return int(state.get("remaining_rounds") or 0)
        return InterviewStageRuntime.remaining_main_question_count(
            BaseInterviewStageSubgraph._stage_progress_from_state(state)
        )

    @staticmethod
    def _stage_event(
        state: ChildState,
        event_type: str,
        *,
        target_stage_id: str | None = None,
    ) -> StageEvent:
        stage_id = BaseInterviewStageSubgraph._stage_id(state)
        target = target_stage_id if target_stage_id in INTERVIEW_STAGE_BY_ID else None
        return {
            "type": event_type,
            "stage_id": stage_id,
            "target_stage_id": target,
            "assistant_message": str(state.get("assistant_message") or ""),
            "response_source": str(state.get("response_source") or "llm"),
            "response_stage_id": stage_id,
            "requested_stage_jump": target,
            "stage_outcome": state.get("stage_outcome", {}),
            "mention": str(state.get("user_message") or "").strip()[:160],
        }


class ConfiguredInterviewStageSubgraph(BaseInterviewStageSubgraph):
    """Default stage implementation driven by interview stage config."""


InterviewStageSubgraph = ConfiguredInterviewStageSubgraph
