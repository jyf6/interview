from fastapi import APIRouter, Request

from app.core.config import settings

router = APIRouter()


@router.get("/health")
async def health_check(request: Request) -> dict[str, str]:
    redis_status = "ok"
    try:
        await request.app.state.redis.ping()
    except Exception:
        redis_status = "unavailable"

    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "redis": redis_status,
    }

