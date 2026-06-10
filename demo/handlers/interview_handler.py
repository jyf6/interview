"""
采访对话处理器
负责正常的采访对话，对齐落地方案 §4.3
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from core.llm_client import llm_client
from core.models import SessionState, ChatResponse
from core.session_manager import session_manager
from config.prompts_config import INTERVIEW_SYSTEM_PROMPT, INTERVIEW_USER_PROMPT_TEMPLATE
from handlers.emotion_handler import analyze_single_message_emotion

logger = logging.getLogger(__name__)


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
    emotion = analyze_single_message_emotion(session, user_message)

    interview_topic = "用户的人生经历"
    user_emotion = emotion.primary_emotion

    interview_context = INTERVIEW_USER_PROMPT_TEMPLATE.format(
        interview_topic=interview_topic,
        user_emotion=user_emotion,
    )

    messages = [SystemMessage(content=INTERVIEW_SYSTEM_PROMPT)]

    for msg in session.chat_history[-20:]:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(
        content=f"{interview_context}\n\n用户最新输入：{user_message}"
    ))

    try:
        response = llm_client.llm.invoke(messages)
        assistant_text = response.content if hasattr(response, "content") else str(response)
        assistant_text = assistant_text.strip()
    except Exception as e:
        logger.warning("LLM 采访对话失败: %s", e)
        assistant_text = "您说的这些很有意思，能再多说一点吗？"

    display_text = f"{assistant_text}\n\n（{emotion.to_display_text()}）"
    session_manager.append_chat(session, "assistant", display_text)

    return ChatResponse(
        session_id=session.session_id,
        state=session.current_state.value,
        assistant_text=display_text,
        can_continue=True,
    )
