"""
会话管理器
Demo 阶段使用内存存储，后续可替换为 Redis
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from .models import SessionState, SystemState

_sessions: dict[str, SessionState] = {}


class SessionManager:
    """会话生命周期管理"""

    def create_session(self, user_id: str) -> SessionState:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"

        session = SessionState(
            session_id=session_id,
            user_id=user_id,
            current_state=SystemState.INIT,
        )

        _sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        return _sessions.get(session_id)

    def update_session(self, session: SessionState) -> SessionState:
        session.updated_at = datetime.now(timezone.utc)
        _sessions[session.session_id] = session
        return session

    def append_chat(self, session: SessionState, role: str, content: str) -> SessionState:
        session.chat_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return self.update_session(session)

    def delete_session(self, session_id: str):
        _sessions.pop(session_id, None)


session_manager = SessionManager()