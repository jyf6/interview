import json
from datetime import UTC, datetime
from uuid import uuid4

from redis.asyncio import Redis

from app.core.config import settings
from app.schemas.agent import (
    AgentMessageCreate,
    AgentMessageRead,
    AgentSessionCreate,
    AgentSessionRead,
)


class SessionStore:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def create_session(self, payload: AgentSessionCreate) -> AgentSessionRead:
        now = datetime.now(UTC)
        session = AgentSessionRead(
            session_id=str(uuid4()),
            user_id=payload.user_id,
            goal=payload.goal,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )

        key = self._session_key(session.session_id)
        await self.redis.set(key, session.model_dump_json(), ex=settings.session_ttl_seconds)
        return session

    async def get_session(self, session_id: str) -> AgentSessionRead | None:
        raw = await self.redis.get(self._session_key(session_id))
        if raw is None:
            return None
        return AgentSessionRead.model_validate_json(raw)

    async def append_message(self, session_id: str, payload: AgentMessageCreate) -> AgentMessageRead:
        now = datetime.now(UTC)
        message = AgentMessageRead(
            message_id=str(uuid4()),
            session_id=session_id,
            role=payload.role,
            content=payload.content,
            created_at=now,
        )

        messages_key = self._messages_key(session_id)
        session = await self.get_session(session_id)
        if session is not None:
            await self.redis.set(
                self._session_key(session_id),
                session.model_copy(update={"updated_at": now}).model_dump_json(),
                ex=settings.session_ttl_seconds,
            )
        await self.redis.rpush(messages_key, message.model_dump_json())
        await self.redis.expire(messages_key, settings.session_ttl_seconds)
        return message

    async def list_messages(self, session_id: str) -> list[AgentMessageRead]:
        raw_messages = await self.redis.lrange(self._messages_key(session_id), 0, -1)
        return [AgentMessageRead.model_validate(json.loads(item)) for item in raw_messages]

    @staticmethod
    def _session_key(session_id: str) -> str:
        return f"agent:session:{session_id}"

    @staticmethod
    def _messages_key(session_id: str) -> str:
        return f"agent:session:{session_id}:messages"

