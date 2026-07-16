from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langgraph.graph import END, StateGraph
from langgraph.types import Command

from app.data.interview_stage_config import FIRST_INTERVIEW_STAGE, INTERVIEW_STAGE_BY_ID, INTERVIEW_STAGE_IDS
from app.graphs.interview_graph_state import ParentState, StageEvent
from app.graphs.interview_stage_subgraph import InterviewStageSubgraph
from app.services.interview_agent_service import InterviewAgentService


class InterviewParentGraph:
    """Macro interview graph.

    Parent state is the interview-level timeline. Per-stage questioning state
    lives in the child stage graph checkpoints.
    """

    def __init__(self, agent: InterviewAgentService, *, checkpointer: Any | None = None) -> None:
        # 创建子图和父图
        self.stage_subgraphs = {
            stage_id: InterviewStageSubgraph(agent, stage_id=stage_id, checkpointer=checkpointer)
            for stage_id in INTERVIEW_STAGE_IDS
        }
        self.graph = self._build_graph(checkpointer=checkpointer)
# 给外界的访问接口
    async def run_turn(self, state: ParentState) -> ParentState:
        return await self.graph.ainvoke(state, self._graph_config(state.get("session_id")))
# 检查当前图的状态//暂时没有使用
    async def get_checkpointed_state(self, session_id: str) -> dict[str, Any] | None:
        # langgrpah方法根据id获取图最近一次的快照
        snapshot = await self.graph.aget_state(self._graph_config(session_id))
        return dict(snapshot.values) if isinstance(snapshot.values, dict) else None
# 获取子图的状态
    async def get_stage_state(self, session_id: str, stage_id: str) -> dict[str, Any] | None:
        subgraph = self.stage_subgraphs.get(stage_id)
        if subgraph is None:
            return None
        return await subgraph.get_checkpointed_state(session_id, stage_id)
# 删除快照
# TODO：不知道在干什么

    async def delete_checkpoint_thread(self, session_id: str) -> None:
        checkpointer = getattr(self.graph, "checkpointer", None)
        if checkpointer is not None:
            await checkpointer.adelete_thread(f"interview-parent:{session_id}")
        for subgraph in self.stage_subgraphs.values():
            await subgraph.delete_checkpoint_thread(session_id)
# 构建父图
    def _build_graph(self, *, checkpointer: Any | None = None) -> Any:
        graph = StateGraph(ParentState)
        graph.add_node("select_stage", self._select_stage)  # 添加选择阶段节点
        graph.add_node("advance_stage", self._advance_stage)
        # 根据子图的返回值决定下一步动作，可以认为是路由节点
        # 子图
        for stage_id, subgraph in self.stage_subgraphs.items():
            graph.add_node(stage_id, subgraph.as_parent_node())
        graph.set_entry_point("select_stage")  # 设置入口节点为选择阶段节点
        return graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _graph_config(session_id: str | None) -> dict[str, dict[str, str]]:
        thread_id = session_id or f"ephemeral:{uuid4()}"
        return {"configurable": {"thread_id": f"interview-parent:{thread_id}"}}

    async def _select_stage(self, state: ParentState) -> Command:
        # 检查如果已经完成采访就结束流转到结束节点
        if int(state.get("completed", 0)):
            return Command(goto=END)
        # 获取当前所处阶段的id
        stage_id = self._stage_id_from_state(state)

        update = self._enter_stage_update(state, stage_id)
        # 更新父状态，记录每个阶段的状态，那些开始了，那些还没开始，那些暂停了
        return Command(goto=stage_id, update=update)

    async def _advance_stage(self, state: ParentState) -> Command:
        event = self._valid_stage_event(state.get("stage_event"), self._stage_id_from_state(state))
        event_type = event.get("type", "stay")
        if event_type == "jump":
            target_stage_id = event.get("target_stage_id")
            if target_stage_id in INTERVIEW_STAGE_BY_ID and target_stage_id != event["stage_id"]:
                return Command(goto=target_stage_id, update=self._jump_stage_update(state, event))
        if event_type == "complete":
            return Command(goto=END, update=self._complete_stage_update(state, event))
        return Command(goto=END, update=self._stay_stage_update(state, event))

    @staticmethod
    def _stage_id_from_state(state: ParentState) -> str:
        stage_id = str(state.get("stage_id") or FIRST_INTERVIEW_STAGE)
        return stage_id if stage_id in INTERVIEW_STAGE_BY_ID else FIRST_INTERVIEW_STAGE
# 校验事件格式的正确性
    @staticmethod
    def _valid_stage_event(value: Any, fallback_stage_id: str) -> StageEvent:
        if not isinstance(value, dict):
            return {
                "type": "stay",
                "stage_id": fallback_stage_id,
                "target_stage_id": None,
                "assistant_message": "",
                "response_source": "llm",
                "response_stage_id": fallback_stage_id,
                "requested_stage_jump": None,
                "stage_outcome": {},
                "mention": "",
            }
        event_type = value.get("type") if value.get("type") in {"stay", "complete", "jump"} else "stay"
        stage_id = str(value.get("stage_id") or fallback_stage_id)
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            stage_id = fallback_stage_id
        target_stage_id = value.get("target_stage_id")
        target_stage_id = target_stage_id if target_stage_id in INTERVIEW_STAGE_BY_ID else None
        response_stage_id = str(value.get("response_stage_id") or stage_id)
        if response_stage_id not in INTERVIEW_STAGE_BY_ID:
            response_stage_id = stage_id
        return {
            "type": event_type,
            "stage_id": stage_id,
            "target_stage_id": target_stage_id,
            "assistant_message": str(value.get("assistant_message") or ""),
            "response_source": str(value.get("response_source") or "llm"),
            "response_stage_id": response_stage_id,
            "requested_stage_jump": target_stage_id,
            "stage_outcome": value.get("stage_outcome") if isinstance(value.get("stage_outcome"), dict) else {},
            "mention": str(value.get("mention") or "").strip()[:160],
        }
# 通过事件进行更新父图的状态
    def _stay_stage_update(self, state: ParentState, event: StageEvent) -> ParentState:
        stage_id = event["stage_id"]
        return {
            "stage_id": stage_id,
            "completed": int(state.get("completed", 0)),
            "started_stage_id": state.get("started_stage_id") or stage_id,
            "stage_flow": self._upsert_stage_flow_entry(
                self._valid_stage_flow(state.get("stage_flow")),
                stage_id,
                "active",
            ),
            "assistant_message": event.get("assistant_message", ""),
            "response_source": event.get("response_source", "llm"),
            "response_stage_id": event.get("response_stage_id", stage_id),
            "requested_stage_jump": event.get("requested_stage_jump"),
            "cross_stage_current": None,
            "stage_event": None,
        }

    def _jump_stage_update(self, state: ParentState, event: StageEvent) -> ParentState:
        source_stage_id = event["stage_id"]
        target_stage_id = str(event.get("target_stage_id") or FIRST_INTERVIEW_STAGE)
        flow = self._valid_stage_flow(state.get("stage_flow"))
        completed_stage_ids = set(self._stage_ids_by_status(flow, "completed"))
        if source_stage_id not in completed_stage_ids:
            flow = self._upsert_stage_flow_entry(flow, source_stage_id, "pending")
        flow = self._upsert_stage_flow_entry(flow, target_stage_id, "active")
        cross_stage_current = self._build_cross_stage_current(source_stage_id, target_stage_id, event.get("mention", ""))
        pending_mentions = self._valid_stage_mentions(state.get("pending_stage_mentions"))
        pending_mentions.pop(target_stage_id, None)
        return {
            "stage_id": target_stage_id,
            "completed": 0,
            "started_stage_id": state.get("started_stage_id") or source_stage_id,
            "stage_flow": flow,
            "pending_stage_mentions": pending_mentions,
            "cross_stage_mentions": self._append_cross_stage_mention(
                state.get("cross_stage_mentions"),
                {**cross_stage_current, "used": True} if cross_stage_current else None,
            ),
            "cross_stage_current": cross_stage_current,
            "stage_transition_hint": self._jump_transition_hint(source_stage_id, target_stage_id, event.get("mention", "")),
            "assistant_message": "",
            "response_source": "none",
            "response_stage_id": None,
            "requested_stage_jump": target_stage_id,
            "stage_event": None,
        }

    def _complete_stage_update(self, state: ParentState, event: StageEvent) -> ParentState:
        stage_id = event["stage_id"]
        flow = self._upsert_stage_flow_entry(self._valid_stage_flow(state.get("stage_flow")), stage_id, "completed")
        stage_outcomes = dict(state.get("stage_outcomes", {}))
        outcome = event.get("stage_outcome")
        if isinstance(outcome, dict) and outcome:
            stage_outcomes[stage_id] = outcome

        next_stage_id = self._next_stage_id(flow)
        pending_mentions = self._valid_stage_mentions(state.get("pending_stage_mentions"))
        pending_mentions.pop(stage_id, None)
        update: ParentState = {
            "stage_id": stage_id,
            "completed": 0,
            "started_stage_id": state.get("started_stage_id") or stage_id,
            "stage_flow": flow,
            "stage_outcomes": stage_outcomes,
            "pending_stage_mentions": pending_mentions,
            "assistant_message": event.get("assistant_message", ""),
            "response_source": event.get("response_source", "llm"),
            "response_stage_id": event.get("response_stage_id", stage_id),
            "requested_stage_jump": None,
            "cross_stage_current": None,
            "stage_event": None,
        }
        if next_stage_id is None:
            return {**update, "completed": 1}

        transition_hint = self._stage_transition_hint_for(
            next_stage_id,
            previous_stage_id=stage_id,
            pending_mentions=pending_mentions,
            stage_outcomes=stage_outcomes,
        )
        flow = self._upsert_stage_flow_entry(flow, next_stage_id, "active")
        return {
            **update,
            "stage_id": next_stage_id,
            "stage_flow": flow,
            "pending_stage_mentions": pending_mentions,
            "cross_stage_mentions": self._mark_cross_stage_mentions_used(
                state.get("cross_stage_mentions"),
                next_stage_id,
            ),
            "stage_transition_hint": transition_hint,
        }

    def _enter_stage_update(self, state: ParentState, stage_id: str) -> ParentState:
        return {
            "stage_id": stage_id,
            # 更新父状态
            "started_stage_id": state.get("started_stage_id") or stage_id,
            "stage_flow": self._upsert_stage_flow_entry(
                self._valid_stage_flow(state.get("stage_flow")),
                stage_id,
                "active",
            ),
        }

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
            if status not in {"not_started", "pending", "active", "completed"}:
                status = "active"
            entry: dict[str, Any] = {"stage_id": stage_id, "status": status}
            for key in ("entered_at", "completed_at"):
                value_text = str(item.get(key) or "").strip()
                if value_text:
                    entry[key] = value_text
            if isinstance(item.get("completed_main_question_ids"), list):
                entry["completed_main_question_ids"] = item["completed_main_question_ids"]
            result.append(entry)
        return result

    @staticmethod
    def _upsert_stage_flow_entry(
        flow: list[dict[str, Any]],
        stage_id: str,
        status: str,
    ) -> list[dict[str, Any]]:
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            return flow
        now = datetime.now(UTC).isoformat()
        cleaned = [
            item
            for item in flow
            if not (status == "active" and item.get("status") == "active" and item.get("stage_id") != stage_id)
        ]
        existing_index = next((index for index, item in enumerate(cleaned) if item.get("stage_id") == stage_id), None)
        existing = cleaned[existing_index] if existing_index is not None else {}
        entry = {
            **existing,
            "stage_id": stage_id,
            "status": status,
            "entered_at": existing.get("entered_at") or now,
        }
        if status == "completed":
            entry["completed_at"] = existing.get("completed_at") or now
        elif status == "active":
            entry.pop("completed_at", None)
        if existing_index is None:
            return [*cleaned, entry]
        updated = [*cleaned]
        updated[existing_index] = entry
        return updated

    @staticmethod
    def _stage_ids_by_status(flow: list[dict[str, Any]], status: str) -> list[str]:
        return [
            str(item.get("stage_id"))
            for item in flow
            if item.get("status") == status and item.get("stage_id") in INTERVIEW_STAGE_BY_ID
        ]

    def _next_stage_id(self, flow: list[dict[str, Any]]) -> str | None:
        completed = set(self._stage_ids_by_status(flow, "completed"))
        for stage_id in self._stage_ids_by_status(flow, "pending"):
            if stage_id not in completed:
                return stage_id
        for stage_id in INTERVIEW_STAGE_IDS:
            if stage_id not in completed:
                return stage_id
        return None

    @staticmethod
    def _valid_stage_mentions(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            str(stage_id): str(mention).strip()[:160]
            for stage_id, mention in value.items()
            if stage_id in INTERVIEW_STAGE_BY_ID and str(mention).strip()
        }

    @staticmethod
    def _build_cross_stage_current(
        source_stage_id: str,
        target_stage_id: str,
        mention: str,
    ) -> dict[str, Any] | None:
        mention = mention.strip()
        if (
            source_stage_id not in INTERVIEW_STAGE_BY_ID
            or target_stage_id not in INTERVIEW_STAGE_BY_ID
            or source_stage_id == target_stage_id
            or not mention
        ):
            return None
        return {
            "stage_id": target_stage_id,
            "source_stage_id": source_stage_id,
            "mention": mention[:160],
            "created_at": datetime.now(UTC).isoformat(),
            "used": False,
        }

    @staticmethod
    def _append_cross_stage_mention(value: Any, mention: dict[str, Any] | None) -> list[dict[str, Any]]:
        mentions = InterviewParentGraph._valid_cross_stage_mentions(value)
        current = InterviewParentGraph._valid_cross_stage_current(mention)
        if current is None:
            return mentions
        duplicate_index = next(
            (
                index
                for index, item in enumerate(mentions)
                if item.get("stage_id") == current.get("stage_id")
                and item.get("source_stage_id") == current.get("source_stage_id")
                and item.get("mention") == current.get("mention")
            ),
            None,
        )
        if duplicate_index is not None:
            updated = [*mentions]
            updated[duplicate_index] = {**updated[duplicate_index], "used": bool(current.get("used", False))}
            return updated
        return [*mentions, current]

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
            mention = InterviewParentGraph._valid_cross_stage_current(item)
            if mention is not None:
                result.append(mention)
        return result[-20:]

    @staticmethod
    def _mark_cross_stage_mentions_used(value: Any, stage_id: str) -> list[dict[str, Any]]:
        return [
            {**mention, "used": True} if mention.get("stage_id") == stage_id else mention
            for mention in InterviewParentGraph._valid_cross_stage_mentions(value)
        ]

    @staticmethod
    def _stage_transition_hint_for(
        next_stage_id: str,
        *,
        previous_stage_id: str,
        pending_mentions: dict[str, str],
        stage_outcomes: dict[str, dict[str, Any]],
    ) -> str:
        mention = pending_mentions.pop(next_stage_id, "")
        next_name = InterviewParentGraph._stage_name(next_stage_id)
        previous_name = InterviewParentGraph._stage_name(previous_stage_id)
        if mention:
            return f"上一阶段已完成，现在进入{next_name}阶段。用户之前提到过：{mention}。请先自然承接这句话。"
        bridge_hint = str(stage_outcomes.get(previous_stage_id, {}).get("bridge_hint") or "").strip()
        if bridge_hint:
            return f"上一阶段{previous_name}已完成，现在进入{next_name}阶段。衔接提示：{bridge_hint[:120]}"
        return f"上一阶段{previous_name}已完成，现在进入{next_name}阶段。请自然承上启下。"

    @staticmethod
    def _jump_transition_hint(source_stage_id: str, target_stage_id: str, mention: str) -> str:
        source_name = InterviewParentGraph._stage_name(source_stage_id)
        target_name = InterviewParentGraph._stage_name(target_stage_id)
        mention = mention.strip()
        if mention:
            return f"用户刚从{source_name}阶段提到了{target_name}阶段内容：{mention[:120]}。请先接住这句话，再进入当前阶段。"
        return f"用户刚从{source_name}阶段跳转到{target_name}阶段。请自然承接后继续采访。"

    @staticmethod
    def _stage_name(stage_id: str) -> str:
        stage = INTERVIEW_STAGE_BY_ID.get(stage_id, {})
        return str(stage.get("name") or stage_id)
