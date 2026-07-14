import asyncio

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError as RedisResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError


class InterviewSessionStore:
    """Redis persistence boundary for interview sessions."""

    def __init__(self, redis: Redis, ttl_seconds: int):
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def get(self, key: str) -> str | None:
        for attempt in range(2):
            try:
                return await self.redis.get(key)
            except RedisResponseError as exc:
                if "WRONGTYPE" not in str(exc):
                    raise
                await self.delete(key)
                return None
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)
        return None

    async def set(self, key: str, value: str) -> None:
        for attempt in range(2):
            try:
                await self.redis.set(key, value, ex=self.ttl_seconds)
                return
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        for attempt in range(2):
            try:
                await self.redis.hset(key, mapping=mapping)
                await self.redis.expire(key, self.ttl_seconds)
                return
            except RedisResponseError as exc:
                if "WRONGTYPE" not in str(exc):
                    raise
                await self.delete(key)
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)

    async def hgetall(self, key: str) -> dict[str, str]:
        for attempt in range(2):
            try:
                return await self.redis.hgetall(key)
            except RedisResponseError as exc:
                if "WRONGTYPE" not in str(exc):
                    raise
                await self.delete(key)
                return {}
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)
        return {}

    async def rpush(self, key: str, value: str) -> None:
        for attempt in range(2):
            try:
                await self.redis.rpush(key, value)
                await self.redis.expire(key, self.ttl_seconds)
                return
            except RedisResponseError as exc:
                if "WRONGTYPE" not in str(exc):
                    raise
                await self.delete(key)
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        for attempt in range(2):
            try:
                return await self.redis.lrange(key, start, end)
            except RedisResponseError as exc:
                if "WRONGTYPE" not in str(exc):
                    raise
                await self.delete(key)
                return []
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)
        return []

    async def delete(self, key: str) -> None:
        for attempt in range(2):
            try:
                await self.redis.delete(key)
                return
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)

    async def overwrite_value(self, key: str, value: str) -> None:
        await self.set(key, value)

    @staticmethod
    def state_key(session_id: str) -> str:
        return f"interview:state:{session_id}"

    @staticmethod
    def userinfo_key(user_id: str) -> str:
        return f"userinfo:{user_id}"

    @staticmethod
    def interview_progress_key(session_id: str) -> str:
        return f"interview:state_interview:{session_id}"

    @staticmethod
    def messages_key(session_id: str) -> str:
        return f"interview:messages:{session_id}"
