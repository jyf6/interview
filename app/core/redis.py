from redis.asyncio import Redis

from app.core.config import settings


def init_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def close_redis(redis: Redis) -> None:
    await redis.aclose()

