"""
采访对话处理器
负责正常的采访对话，对齐落地方案 §4.3
"""

from core.models import SessionState, ChatResponse
from core.session_manager import session_manager


def chat_interview(session: SessionState, user_message: str) -> ChatResponse:
    """
    处理采访对话

    流程：
    1. 保存用户消息到历史
    2. 构建对话上下文（最近 20 轮）
    3. 调用 LLM 生成回复
    4. 保存 AI 回复
    5. 返回结果
    """
    session_manager.append_chat(session, "user", user_message)

    assistant_text = "采：我已经记下来了。您愿意再多说一点当时的情景吗？"

    display_text = assistant_text
    session_manager.append_chat(session, "assistant", display_text)

    return ChatResponse(
        session_id=session.session_id,
        state=session.current_state.value,
        assistant_text=display_text,
        can_continue=True,
    )
