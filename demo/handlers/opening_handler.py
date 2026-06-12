"""
开场白处理器
负责生成定制化开场白，对齐落地方案 §4.1
"""

import json
import logging

from core.llm_client import llm_client
from core.models import SessionState, OpeningOutput, SuggestedCard, RiskNotes, SessionResponse
from core.state_machine import state_machine
from core.session_manager import session_manager
from config.prompts_config import OPENING_SYSTEM_PROMPT, OPENING_USER_PROMPT_TEMPLATE
from config.cards_config import get_main_cards

logger = logging.getLogger(__name__)


def generate_opening(session: SessionState) -> SessionResponse:
    """生成开场白并更新会话状态"""
    state_machine.transition(session, "OPENING_GENERATING", "开始生成开场白")

    profile = session.session_context.is_first_visit

    user_profile_json = json.dumps({
        "nickname": session.user_profile.nickname,
        "age_range": session.user_profile.age_range,
        "known_life_stage": session.user_profile.known_life_stage,
        "communication_preference": session.user_profile.communication_preference,
        "avoid_topics": session.user_profile.avoid_topics,
    }, ensure_ascii=False)

    session_context_json = json.dumps({
        "is_first_visit": session.session_context.is_first_visit,
        "last_state": session.session_context.last_state.value if session.session_context.last_state else None,
        "last_story_summary": session.session_context.last_story_summary,
        "unfinished_slots": session.session_context.unfinished_slots,
        "days_since_last_visit": session.session_context.days_since_last_visit,
    }, ensure_ascii=False)

    business_context_json = json.dumps({
        "product_role": "传记记录助手",
        "tone": "温和、尊重、像采访者",
        "max_opening_sentences": 3,
    }, ensure_ascii=False)

    user_prompt = OPENING_USER_PROMPT_TEMPLATE.format(
        user_profile=user_profile_json,
        session_context=session_context_json,
        business_context=business_context_json,
    )

    try:
        result = llm_client.chat_json(OPENING_SYSTEM_PROMPT, user_prompt)
        opening = OpeningOutput(
            opening_type=result.get("opening_type", "first_user"),
            main_message=result.get("main_message", ""),
            trust_sentence=result.get("trust_sentence", ""),
            micro_question=result.get("micro_question", ""),
            suggested_cards=[SuggestedCard(**card) for card in get_main_cards()],
            risk_notes=RiskNotes(**result.get("risk_notes", {})),
        )
    except Exception as e:
        logger.warning("LLM 开场白生成失败，使用默认话术: %s", e)
        opening = _default_opening(session)

    session_manager.append_chat(session, "assistant", opening.main_message)
    state_machine.transition(session, "OPENING_DELIVERED", "开场白已送达")
    session_manager.update_session(session)

    return SessionResponse(
        session_id=session.session_id,
        state=session.current_state.value if hasattr(session.current_state, 'value') else session.current_state,
        message=opening,
        cards=opening.suggested_cards,
    )


def _default_opening(session: SessionState) -> OpeningOutput:
    """默认开场白（LLM 不可用时的降级方案）"""
    is_first = session.session_context.is_first_visit
    if is_first:
        return OpeningOutput(
            opening_type="first_user",
            main_message="您好，我会像一位安静的记录者，陪您把重要经历慢慢整理下来。",
            trust_sentence="这里没有标准答案，我们慢慢来。",
            micro_question="您小时候主要住在哪里？",
            suggested_cards=[
                SuggestedCard(card_id="start_interview", label="直接开始采访", next_action="ENTER_INTERVIEW"),
                SuggestedCard(card_id="need_guidance", label="我还没想好怎么说", next_action="SHOW_GUIDANCE_CARD"),
            ],
            risk_notes=RiskNotes(),
        )
    else:
        summary = session.session_context.last_story_summary or "上次聊的内容"
        return OpeningOutput(
            opening_type="resume_user",
            main_message=f"欢迎回来。{summary}，我们可以接着聊。",
            trust_sentence="不用着急，想到哪说到哪。",
            micro_question="要不要从上次说的地方继续？",
            suggested_cards=[
                SuggestedCard(card_id="start_interview", label="继续讲这个故事", next_action="ENTER_INTERVIEW"),
                SuggestedCard(card_id="need_guidance", label="我还没想好怎么说", next_action="SHOW_GUIDANCE_CARD"),
            ],
            risk_notes=RiskNotes(),
        )
