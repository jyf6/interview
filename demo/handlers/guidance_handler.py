"""
卡片引导处理器
负责处理用户心理状态卡片选择，对齐落地方案 §4.2
"""

import json
import logging

from core.llm_client import llm_client
from core.models import SessionState, GuidanceOutput, GuidanceCard, SessionResponse, SuggestedCard
from core.state_machine import state_machine
from core.session_manager import session_manager
from config.prompts_config import GUIDANCE_SYSTEM_PROMPT, GUIDANCE_USER_PROMPT_TEMPLATE
from config.cards_config import get_card_by_id, get_psychology_cards

logger = logging.getLogger(__name__)


def handle_card_selection(session: SessionState, card_id: str) -> SessionResponse:
    """
    处理心理状态卡片选择，生成引导话术

    对齐落地方案 §4.2：用户选择心理状态卡片 →
    1. 返回对应的安抚/引导话术
    2. 提供「开始采访」卡片，用户可随时进入采访
    """
    card = get_card_by_id(card_id)
    if card is None:
        return SessionResponse(
            session_id=session.session_id,
            state=session.current_state.value if hasattr(session.current_state, 'value') else session.current_state,
            assistant_text="抱歉，我没有理解您的选择，请再试一次。",
            cards=[
                SuggestedCard(card_id=c["card_id"], label=c["label"], next_action="PSYCHOLOGY_CARD_SELECTED")
                for c in get_psychology_cards()
            ],
        )

    user_profile_json = json.dumps({
        "nickname": session.user_profile.nickname,
        "age_range": session.user_profile.age_range,
        "communication_preference": session.user_profile.communication_preference,
    }, ensure_ascii=False)

    session_context_json = json.dumps({
        "current_state": session.current_state.value if hasattr(session.current_state, 'value') else str(session.current_state),
        "chat_rounds": len(session.chat_history),
    }, ensure_ascii=False)

    user_prompt = GUIDANCE_USER_PROMPT_TEMPLATE.format(
        selected_card_label=card["label"],
        user_psychology=card["user_psychology"],
        card_id=card_id,
        user_profile=user_profile_json,
        session_context=session_context_json,
        base_corpus=card["assistant_message"],
    )

    try:
        result = llm_client.chat_json(GUIDANCE_SYSTEM_PROMPT, user_prompt)

        guidance = GuidanceOutput(
            selected_card_id=card_id,
            response_strategy=result.get("response_strategy", ""),
            assistant_message=result.get("assistant_message", card["assistant_message"]),
            next_question=result.get("next_question", card["next_question"]),
            next_cards=[],
            can_enter_interview=result.get("can_enter_interview", True),
            recommended_next_state=result.get("recommended_next_state", "GUIDANCE_CARD"),
        )
    except Exception as e:
        logger.warning("LLM 引导生成失败，使用基础语料: %s", e)
        guidance = GuidanceOutput(
            selected_card_id=card_id,
            response_strategy=card["response_strategy"],
            assistant_message=card["assistant_message"],
            next_question=card["next_question"],
            next_cards=[],
            can_enter_interview=True,
            recommended_next_state="GUIDANCE_CARD",
        )

    session_manager.append_chat(session, "assistant", guidance.assistant_message)

    to_state = guidance.recommended_next_state
    state_machine.transition(session, to_state, f"用户选择卡片: {card_id}")
    session_manager.update_session(session)

    # 引导后始终提供「开始采访」+「再看看其他卡片」
    response_cards = [
        SuggestedCard(card_id="start_interview", label="开始采访", next_action="ENTER_INTERVIEW"),
        SuggestedCard(card_id="need_guidance", label="再看看其他卡片", next_action="SHOW_GUIDANCE_CARD"),
    ]

    current_state = session.current_state.value if hasattr(session.current_state, 'value') else str(session.current_state)

    return SessionResponse(
        session_id=session.session_id,
        state=current_state,
        guidance=guidance,
        cards=response_cards,
        assistant_text=guidance.assistant_message,
    )


def get_guidance_cards(session: SessionState) -> SessionResponse:
    """展示心理状态卡片"""
    state_machine.transition(session, "GUIDANCE_CARD", "展示心理状态卡片")
    session_manager.update_session(session)

    cards = [
        GuidanceCard(card_id=c["card_id"], label=c["label"], next_action="PSYCHOLOGY_CARD_SELECTED")
        for c in get_psychology_cards()
    ]

    return SessionResponse(
        session_id=session.session_id,
        state=session.current_state.value,
        cards=[SuggestedCard(card_id=c.card_id, label=c.label, next_action=c.next_action) for c in cards],
        assistant_text="没关系的，您可以告诉我您现在是什么状态，我会根据您的情况来调整。",
    )
