"""
银发传记 - 引导模块 Demo
========================
FastAPI 入口，提供会话管理、开场白、卡片引导、采访对话 API。

启动方式：
    python main.py

API 端点：
    GET  /api/onboarding/guide       - 获取产品入场引导
    POST /api/session/start          - 创建/恢复会话，获取开场白
    POST /api/session/{id}/card      - 提交卡片选择
    POST /api/session/{id}/guidance  - 展示心理状态卡片
    POST /api/session/{id}/chat      - 采访对话
    POST /api/session/{id}/enter     - 进入采访阶段
    GET  /api/session/{id}           - 查询会话状态
"""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config.app_config import app_config
from core.models import (
    SessionState,
    StartSessionRequest,
    CardSelectRequest,
    ChatRequest,
    SessionResponse,
    ChatResponse,
    OnboardingGuideResponse,
)
from core.state_machine import state_machine
from core.session_manager import session_manager
from handlers.opening_handler import generate_opening
from handlers.guidance_handler import handle_card_selection, get_guidance_cards
from handlers.interview_handler import chat_interview
from handlers.onboarding_handler import get_onboarding_guide

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("silver_bio")

app = FastAPI(
    title="银发传记引导模块 Demo",
    description="基于状态机的银发传记采访引导系统",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== 辅助函数 =====

def _get_session(session_id: str) -> SessionState:
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


# ===== API 端点 =====

@app.get("/api/onboarding/guide", response_model=OnboardingGuideResponse)
def onboarding_guide():
    """获取产品入场引导配置。"""
    return get_onboarding_guide()


@app.post("/api/session/start", response_model=SessionResponse)
def session_start(req: StartSessionRequest):
    """
    创建或恢复会话，返回开场白。

    流程：
    1. 创建新会话（或后续对接恢复逻辑）
    2. 状态：INIT -> OPENING_GENERATING -> OPENING_DELIVERED
    3. 返回定制开场白和建议卡片
    """
    session = session_manager.create_session(req.user_id)
    session.user_profile.nickname = req.user_id
    logger.info("新会话创建: session_id=%s user_id=%s", session.session_id, req.user_id)

    response = generate_opening(session)
    logger.info("开场白生成完成: session_id=%s state=%s", session.session_id, response.state)
    return response


@app.post("/api/session/{session_id}/card", response_model=SessionResponse)
def session_card_select(session_id: str, req: CardSelectRequest):
    """
    用户选择卡片后的处理。对齐落地方案 §4.1.3 和 §4.2。

    流程：
    - start_interview → 直接进入 INTERVIEWING 采访阶段
    - need_guidance   → 展示 6 种心理状态引导卡片
    - relaxed_slow / emotional_memory / unknown_process / restrained / enthusiastic / scattered: 心理状态卡片
    """
    session = _get_session(session_id)

    if req.card_id == "start_interview":
        # 对齐落地方案 §3.3: OPENING_DELIVERED/GUIDANCE_CARD → INTERVIEWING
        current = session.current_state.value if hasattr(session.current_state, 'value') else str(session.current_state)
        if current not in ("INTERVIEWING",):
            if current != "READY_TO_INTERVIEW":
                state_machine.transition(session, "READY_TO_INTERVIEW", "用户确认开始采访")
            state_machine.transition(session, "INTERVIEWING", "采访开始")
        session_manager.update_session(session)
        logger.info("用户进入采访: session_id=%s", session_id)
        return SessionResponse(
            session_id=session_id,
            state=session.current_state.value if hasattr(session.current_state, 'value') else session.current_state,
            assistant_text="好的，我们正式开始。您想到哪里就说到哪里，随便聊聊。",
        )

    if req.card_id == "need_guidance":
        return get_guidance_cards(session)

    return handle_card_selection(session, req.card_id)


@app.post("/api/session/{session_id}/guidance", response_model=SessionResponse)
def session_show_guidance(session_id: str):
    """展示心理状态选择卡片"""
    session = _get_session(session_id)
    return get_guidance_cards(session)


@app.post("/api/session/{session_id}/enter", response_model=SessionResponse)
def session_enter_interview(session_id: str):
    """手动进入采访阶段"""
    session = _get_session(session_id)
    current = session.current_state.value if hasattr(session.current_state, 'value') else session.current_state

    if current not in ("INTERVIEWING",):
        if current != "READY_TO_INTERVIEW":
            state_machine.transition(session, "READY_TO_INTERVIEW", "用户确认进入采访")
        state_machine.transition(session, "INTERVIEWING", "采访开始")
    session_manager.update_session(session)
    logger.info("进入采访阶段: session_id=%s", session_id)
    return SessionResponse(
        session_id=session_id,
        state=session.current_state.value if hasattr(session.current_state, 'value') else session.current_state,
        assistant_text="好的，我们现在正式开始。您可以随意说，想到哪里就说到哪里。",
    )


@app.post("/api/session/{session_id}/chat", response_model=ChatResponse)
def session_chat(session_id: str, req: ChatRequest):
    """
    采访对话接口。

    要求当前状态为 INTERVIEWING 或 READY_TO_INTERVIEW。
    如果还在 READY_TO_INTERVIEW，自动切换到 INTERVIEWING。
    """
    session = _get_session(session_id)

    if session.current_state == "READY_TO_INTERVIEW":
        state_machine.transition(session, "INTERVIEWING", "首次对话，进入采访")

    if session.current_state != "INTERVIEWING":
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {session.current_state.value} 不支持对话",
        )

    logger.info("采访对话: session_id=%s message=%s", session_id, req.message[:50])
    response = chat_interview(session, req.message)
    return response


@app.get("/api/session/{session_id}/status", response_model=SessionResponse)
def session_status(session_id: str):
    """查询会话当前状态"""
    session = _get_session(session_id)
    return SessionResponse(
        session_id=session_id,
        state=session.current_state.value,
        assistant_text=f"当前状态: {session.current_state.value}，历史消息数: {len(session.chat_history)}",
    )


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "silver-bio-demo"}


# ===== 启动入口 =====

if __name__ == "__main__":
    import uvicorn

    logger.info("银发传记引导模块 Demo 启动中...")
    logger.info("DashScope 模型: %s", app_config.dashscope_model)
    logger.info("API 文档: http://%s:%s/docs", app_config.server_host, app_config.server_port)

    uvicorn.run(
        "main:app",
        host=app_config.server_host,
        port=app_config.server_port,
        reload=True,
        log_level="debug",
    )
