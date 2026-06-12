"""
状态机控制器
负责管理会话的生命周期状态流转
"""

from datetime import datetime, timezone
from typing import Callable, Optional

from .models import SessionState, SystemState


class StateMachine:
    """
    状态流转规则，与落地方案 §3 对齐。

    核心状态流转：
    INIT -> OPENING_GENERATING -> OPENING_DELIVERED
    OPENING_DELIVERED -> READY_TO_INTERVIEW (选开始) | GUIDANCE_CARD (选顾虑)
    GUIDANCE_CARD -> GUIDANCE_CARD (继续引导) | READY_TO_INTERVIEW (确认开始)
    READY_TO_INTERVIEW -> INTERVIEWING
    INTERVIEWING -> PAUSED (退出) | COMPLETED (完成)
    PAUSED -> RECONNECTING -> (根据断点恢复)
    """

    VALID_TRANSITIONS: dict[SystemState, set[SystemState]] = {
        SystemState.INIT: {SystemState.OPENING_GENERATING},
        SystemState.OPENING_GENERATING: {SystemState.OPENING_DELIVERED},
        SystemState.OPENING_DELIVERED: {SystemState.READY_TO_INTERVIEW, SystemState.GUIDANCE_CARD, SystemState.PAUSED},
        SystemState.GUIDANCE_CARD: {SystemState.GUIDANCE_CARD, SystemState.READY_TO_INTERVIEW, SystemState.PAUSED},
        SystemState.READY_TO_INTERVIEW: {SystemState.INTERVIEWING},
        SystemState.INTERVIEWING: {SystemState.INTERVIEWING, SystemState.PAUSED, SystemState.COMPLETED},
        SystemState.PAUSED: {SystemState.RECONNECTING},
        SystemState.RECONNECTING: {SystemState.OPENING_GENERATING, SystemState.GUIDANCE_CARD, SystemState.INTERVIEWING},
        SystemState.COMPLETED: set(),
    }

    def __init__(self):
        self._on_state_change: list[Callable] = []

    def can_transition(self, from_state: SystemState, to_state: SystemState) -> bool:
        return to_state in self.VALID_TRANSITIONS.get(from_state, set())

    def transition(self, session: SessionState, to_state: "SystemState | str", reason: str = "") -> SessionState:
        # 统一转为枚举，防止调用方传入字符串导致 Pydantic 验证失败
        if isinstance(to_state, str):
            to_state = SystemState(to_state)

        from_value = session.current_state.value if isinstance(session.current_state, SystemState) else session.current_state
        if not self.can_transition(session.current_state, to_state):
            raise ValueError(
                f"非法状态流转: {from_value} -> {to_state.value}"
            )

        session.previous_state = session.current_state
        session.current_state = to_state
        session.updated_at = datetime.now(timezone.utc)

        for callback in self._on_state_change:
            try:
                callback(session, reason)
            except Exception:
                pass

        return session

    def on_state_change(self, callback: Callable):
        self._on_state_change.append(callback)
        return callback

    def get_resume_state(self, session: SessionState) -> SystemState:
        """
        根据中断前的状态，决定重连后的目标状态
        对齐落地方案 §3.4
        """
        prev = session.session_context.last_state
        if prev is None:
            return SystemState.OPENING_GENERATING

        resume_map = {
            SystemState.OPENING_DELIVERED: SystemState.OPENING_GENERATING,
            SystemState.GUIDANCE_CARD: SystemState.GUIDANCE_CARD,
            SystemState.INTERVIEWING: SystemState.INTERVIEWING,
        }
        return resume_map.get(prev, SystemState.OPENING_GENERATING)


state_machine = StateMachine()
