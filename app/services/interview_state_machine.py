import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from redis.asyncio import Redis

from app.core.config import settings
from app.core.perf import perf_span
from app.data.interview_cards import CARD_RESPONSE_CORPUS, ENTRY_CARDS, GUIDANCE_CARDS, normalize_card_id
from app.schemas.interview import (
    DialogActionRequest,
    DialogMessage,
    DialogTextRequest,
    DialogTurnResponse,
    EntryCardSelection,
    GuidanceCardResponse,
    GuidanceCardSelection,
    InterviewCard,
    InterviewContext,
    InterviewState,
    StartInterviewResponse,
)
from app.services.dashscope_llm import DashScopeLLM
from app.services.interview_agent_service import InterviewAgentService
from app.services.opening_service import OpeningService


class InterviewStateMachine:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.llm = DashScopeLLM()
        self.interview_agent = InterviewAgentService()
        self.opening = OpeningService()

    async def start(self) -> StartInterviewResponse:
        response = await self.start_dialog()
        return StartInterviewResponse(
            session_id=response.session_id,
            current_state=response.current_state,
            cards=response.cards,
            assistant_message=response.message.content if response.message else "",
            guidance_round=response.guidance_round,
            max_guidance_rounds=response.max_guidance_rounds,
        )

    async def start_dialog(self, session_id: str | None = None) -> DialogTurnResponse:
        with perf_span("dialog.start", has_session=bool(session_id)):
            context = await self._get_or_create_context(session_id)
            self._transition(context, "OPENING_GENERATING")
            self._transition(context, "OPENING_DELIVERED")
            await self._save_context(context)

        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=context.current_state,
            previous_state=context.previous_state,
            action="show_entry_cards",
            message=self.opening.build_opening_message(),
            cards=self.opening.build_entry_cards(),
            card_group="entry",
            guidance_round=context.guidance_round,
            max_guidance_rounds=context.max_guidance_rounds,
            can_continue_guidance=context.guidance_round < context.max_guidance_rounds,
            response_source="none",
        )

    async def handle_dialog_action(self, payload: DialogActionRequest) -> DialogTurnResponse:
        context = await self._get_or_create_context(payload.session_id)
        card_id = normalize_card_id(payload.card_id)

        if card_id == "start_interview":
            return await self._ready_to_interview(context)

        if card_id == "need_guidance":
            return await self._show_guidance_cards(context)

        return await self._handle_guidance_card(context, card_id)

    async def handle_dialog_text(self, payload: DialogTextRequest) -> DialogTurnResponse:
        with perf_span("dialog.text.total", has_session=bool(payload.session_id), chars=len(payload.content)):
            context = await self._get_or_create_context(payload.session_id)
            if context.current_state == "READY_TO_INTERVIEW":
                self._transition(context, "INTERVIEWING")
            elif context.current_state != "INTERVIEWING":
                self._transition(context, "READY_TO_INTERVIEW")
                self._transition(context, "INTERVIEWING")

            user_content = payload.content.strip()
            context.dialog_messages.append({"role": "user", "content": user_content})

            assistant_content, _emotion = await self.interview_agent.generate_turn(
                user_message=user_content,
                recent_messages=context.dialog_messages,
            )
            context.dialog_messages.append({"role": "assistant", "content": assistant_content})
            context.updated_at = datetime.now(UTC)
            await self._save_context(context)

        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=context.current_state,
            previous_state=context.previous_state,
            action="append_message",
            message=DialogMessage(content=assistant_content),
            cards=[],
            card_group="none",
            guidance_round=context.guidance_round,
            max_guidance_rounds=context.max_guidance_rounds,
            can_continue_guidance=False,
            response_source="llm",
        )

    async def select_entry_card(self, payload: EntryCardSelection) -> StartInterviewResponse:
        response = await self.handle_dialog_action(
            DialogActionRequest(session_id=payload.session_id, card_id=payload.card_id)
        )
        return StartInterviewResponse(
            session_id=response.session_id,
            current_state=response.current_state,
            cards=response.cards,
            guidance_cards=response.cards if response.card_group == "guidance" else [],
            assistant_message=response.message.content if response.message else "",
            guidance_round=response.guidance_round,
            max_guidance_rounds=response.max_guidance_rounds,
        )

    async def select_guidance_card(self, payload: GuidanceCardSelection) -> GuidanceCardResponse:
        response = await self.handle_dialog_action(
            DialogActionRequest(session_id=payload.session_id, card_id=payload.card_id)
        )
        return GuidanceCardResponse(
            session_id=response.session_id,
            assistant_message=response.message.content if response.message else "",
            next_cards=response.cards,
            recommended_next_state=response.current_state,
            current_state=response.current_state,
            guidance_round=response.guidance_round,
            max_guidance_rounds=response.max_guidance_rounds,
            can_continue_guidance=response.can_continue_guidance,
            response_source=response.response_source if response.response_source != "none" else "fallback",
        )

    async def _ready_to_interview(self, context: InterviewContext) -> DialogTurnResponse:
        self._transition(context, "READY_TO_INTERVIEW")
        context.dialog_messages.append(
            {
                "role": "assistant",
                "content": "好的，我们准备开始采访。您可以从一个人、一个地方，或一件小事慢慢说起。",
            }
        )
        await self._save_context(context)
        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=context.current_state,
            previous_state=context.previous_state,
            action="ready_to_interview",
            message=DialogMessage(content="好的，我们准备开始采访。您可以从一个人、一个地方，或一件小事慢慢说起。"),
            cards=[],
            card_group="none",
            guidance_round=context.guidance_round,
            max_guidance_rounds=context.max_guidance_rounds,
            can_continue_guidance=False,
            response_source="none",
        )

    async def _show_guidance_cards(self, context: InterviewContext) -> DialogTurnResponse:
        self._transition(context, "GUIDANCE_CARD")
        await self._save_context(context)

        if context.guidance_round >= context.max_guidance_rounds:
            return DialogTurnResponse(
                session_id=context.session_id,
                current_state=context.current_state,
                previous_state=context.previous_state,
                action="show_entry_cards",
                message=DialogMessage(content="我们已经慢慢准备了几次。现在可以先轻轻开始，过程中仍然可以随时停下来。"),
                cards=self._cards([ENTRY_CARDS[0]]),
                card_group="entry",
                guidance_round=context.guidance_round,
                max_guidance_rounds=context.max_guidance_rounds,
                can_continue_guidance=False,
                response_source="none",
            )

        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=context.current_state,
            previous_state=context.previous_state,
            action="show_guidance_cards",
            message=DialogMessage(content="没关系，您可以先选一个最接近现在感受的卡片，我会把接下来的问题调得更轻一点。"),
            cards=self._cards(GUIDANCE_CARDS),
            card_group="guidance",
            guidance_round=context.guidance_round,
            max_guidance_rounds=context.max_guidance_rounds,
            can_continue_guidance=True,
            response_source="none",
        )

    async def _handle_guidance_card(self, context: InterviewContext, card_id: str) -> DialogTurnResponse:
        corpus = CARD_RESPONSE_CORPUS.get(card_id)
        if corpus is None:
            return DialogTurnResponse(
                session_id=context.session_id,
                current_state=context.current_state,
                previous_state=context.previous_state,
                action="show_guidance_cards",
                message=DialogMessage(content="抱歉，我没有理解这个选择。您可以重新选一张更接近当前感受的卡片。"),
                cards=self._cards(GUIDANCE_CARDS),
                card_group="guidance",
                guidance_round=context.guidance_round,
                max_guidance_rounds=context.max_guidance_rounds,
                can_continue_guidance=context.guidance_round < context.max_guidance_rounds,
                response_source="fallback",
            )

        generated = await self.llm.generate_guidance_response(
            card_id=card_id,
            card_corpus=corpus,
            fallback_message=corpus["response"],
        )

        self._transition(context, "GUIDANCE_CARD")
        if context.guidance_round < context.max_guidance_rounds:
            context.guidance_round += 1
        context.updated_at = datetime.now(UTC)
        await self._save_context(context)

        can_continue = context.guidance_round < context.max_guidance_rounds
        next_cards = ENTRY_CARDS if can_continue else [ENTRY_CARDS[0]]
        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=context.current_state,
            previous_state=context.previous_state,
            action="append_message",
            message=DialogMessage(content=generated["assistant_message"]),
            cards=self._cards(next_cards),
            card_group="entry",
            guidance_round=context.guidance_round,
            max_guidance_rounds=context.max_guidance_rounds,
            can_continue_guidance=can_continue,
            response_source=generated["response_source"],
        )

    async def _get_or_create_context(self, session_id: str | None = None) -> InterviewContext:
        if session_id:
            context = await self._get_context(session_id)
            if context is not None:
                return context
        return await self._create_context(session_id)

    async def _create_context(self, session_id: str | None = None) -> InterviewContext:
        now = datetime.now(UTC)
        context = InterviewContext(
            session_id=session_id or str(uuid4()),
            current_state="INIT",
            created_at=now,
            updated_at=now,
        )
        await self._save_context(context)
        return context

    async def _get_context(self, session_id: str) -> InterviewContext | None:
        raw = await self._redis_get(self._key(session_id))
        if raw is None:
            return None
        return InterviewContext.model_validate_json(raw)

    async def _save_context(self, context: InterviewContext) -> None:
        await self._redis_set(self._key(context.session_id), context.model_dump_json())

    async def _redis_get(self, key: str) -> str | None:
        for attempt in range(2):
            try:
                return await self.redis.get(key)
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)
        return None

    async def _redis_set(self, key: str, value: str) -> None:
        for attempt in range(2):
            try:
                await self.redis.set(key, value, ex=settings.session_ttl_seconds)
                return
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)

    @staticmethod
    def _transition(context: InterviewContext, to_state: InterviewState) -> None:
        if context.current_state != to_state:
            context.previous_state = context.current_state
            context.current_state = to_state
        context.updated_at = datetime.now(UTC)

    @staticmethod
    def _cards(raw_cards: list[dict[str, str]]) -> list[InterviewCard]:
        return [InterviewCard(**card) for card in raw_cards]

    @staticmethod
    def _key(session_id: str) -> str:
        return f"interview:state:{session_id}"
