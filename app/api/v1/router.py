from fastapi import APIRouter

from app.api.v1.routes import biography, health, interview

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(interview.router, tags=["interview"])
api_router.include_router(biography.router, tags=["biography"])
