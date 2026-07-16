from typing import Any, Literal, TypedDict


StageRouteName = Literal[
    "normal_answer",
    "extended_probe",
    "low_information",
    "off_stage_reference",
    "stage_complete",
    "emotional_blocked",
]


class ParentState(TypedDict, total=False):
    session_id: str
    interviewee_id: str | None
    stage_id: str
    completed: int
    started_stage_id: str | None
    stage_flow: list[dict[str, Any]]
    stage_outcomes: dict[str, dict[str, Any]]
    pending_stage_mentions: dict[str, str]
    cross_stage_mentions: list[dict[str, Any]]
    cross_stage_current: dict[str, Any] | None
    stage_transition_hint: str
    local_messages: list[dict[str, str]]
    stage_messages: dict[str, list[dict[str, str]]]
    stage_seed: dict[str, Any]
    global_messages: list[dict[str, str]]
    global_outline: dict[str, Any]
    user_message: str
    assistant_message: str
    response_source: str
    response_stage_id: str | None
    requested_stage_jump: str | None
    stage_event: "StageEvent | None"
    active_thread_id: str
    active_point_id: str
    point_snapshot: dict[str, Any]
    thread_stack: list[dict[str, Any]]
    diversion: dict[str, Any] | None
    diversion_turns: int
    last_semantic_route: dict[str, Any] | None


class ChildState(TypedDict, total=False):
    session_id: str
    stage_id: str
    local_messages: list[dict[str, str]]
    user_message: str
    stage_description: str
    remaining_rounds: int
    stage_transition_hint: str
    cross_stage_current: dict[str, Any] | None
    stage_outcomes: dict[str, dict[str, Any]]
    global_outline: dict[str, Any]
    completed_main_question_ids: list[int]
    active_main_question_id: int | None
    awaiting_stage_completion: int
    supplement_answered: int
    probe_count: int
    missing_info: list[str]
    stage_route: dict[str, Any]
    turn_route: dict[str, Any]
    legacy_route_name: str
    assistant_message: str
    response_source: str
    main_question_id: int | None
    answer_counted: bool
    stage_complete: bool
    stage_outcome: dict[str, Any]
    requested_stage_jump: str | None
    stage_event: "StageEvent | None"


StageEventType = Literal["stay", "complete", "jump"]


class StageEvent(TypedDict, total=False):
    type: StageEventType
    stage_id: str
    target_stage_id: str | None
    assistant_message: str
    response_source: str
    response_stage_id: str
    requested_stage_jump: str | None
    stage_outcome: dict[str, Any]
    mention: str
