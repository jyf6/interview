import asyncio
import json
import random
from datetime import UTC, datetime
from typing import cast, get_args
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

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
    InterviewStateResponse,
    StartInterviewResponse,
    UserInfoRequest,
    UserInfoResponse,
)
from app.services.dashscope_llm import DashScopeLLM
from app.services.interview_agent_service import InterviewAgentService
from app.services.opening_service import OpeningService

VALID_INTERVIEW_STATES = set(get_args(InterviewState))
MAX_GUIDANCE_ROUNDS = 3
GUIDANCE_LIMIT_MESSAGES = [
    "不用有任何担心和顾虑哦。整个采访过程轻松自由，没有复杂规则，如果你对流程有任何不明白的地方，随时都可以问我。一切都按照你的节奏进行，你可以安心放心地点击开启采访，我们慢慢聊就好。",
    "我能理解你对未知流程的小忐忑，其实完全不用紧张。全程都是轻松聊天，有任何疑问、不清楚的地方都可以随时提问。你可以放心大胆开启采访，不用拘谨，随心分享就足够啦。",
    "放宽心呀，不用害怕不熟悉采访流程。过程非常简单随意，遇到不懂的地方随时和我说就可以。我会全程耐心陪伴、为你解答，你尽管安心点击开启，自在分享你的人生故事就好。",
    "不用顾虑太多，这场交流没有压力、没有标准答案。无论你哪里不清楚、想了解任何细节，都可以随时发问。请放心开启本次采访，我会一直耐心倾听、陪着你慢慢完成分享。",
    "或许你现在还有一点点不确定感，这完全没关系。你在采访途中有任何疑问、对流程有困惑，随时都能停下来问我。放轻松、不用紧张，安心点击开启采访就好。",
    "不用给自己压力，也不用担忧流程问题。全程都是轻松治愈的闲聊方式，有任何不懂的地方随时沟通就行。你可以彻底放心，主动开启采访，我们温柔、自在地慢慢畅谈你的故事。",
    "别担心，采访听起来可能有点正式，但在这里它更像一次轻松聊天。你不用提前准备，也不用担心自己说得不够好；我会跟着你的节奏慢慢来。过程中你随时可以问我、暂停一下，或者跳过不想聊的内容。你只需要把舒服放在第一位。",
]


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

    async def start_dialog(self, session_id: str | None = None, user_id: str | None = None) -> DialogTurnResponse:
        with perf_span("dialog.start", has_session=bool(session_id)):
            context = await self._get_or_create_context(session_id)
            await self._transition(context, "OPENING_GENERATING")
            userinfo = await self._get_userinfo(user_id) if user_id else {}
            opening_message = await self.opening.build_opening_message(userinfo=userinfo)
            await self._transition(context, "OPENING_DELIVERED")
            guidance_round = await self._get_guidance_round(context.session_id)

        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=self._current_state(context),
            previous_state=context.previous_state,
            action="show_entry_cards",
            message=opening_message,
            cards=self.opening.build_entry_cards(),
            card_group="entry",
            guidance_round=guidance_round,
            max_guidance_rounds=MAX_GUIDANCE_ROUNDS,
            can_continue_guidance=guidance_round < MAX_GUIDANCE_ROUNDS,
            response_source="none",
        )

    async def handle_dialog_action(self, payload: DialogActionRequest) -> DialogTurnResponse:
        context = await self._get_or_create_context(payload.session_id)
        card_id = normalize_card_id(payload.card_id)

        if card_id == "start_interview":
            return await self._ready_to_interview(context)

        if card_id == "need_guidance":
            return await self._show_guidance_cards(context)

        return await self._handle_guidance_card(context, card_id, payload.question)

    async def handle_dialog_text(self, payload: DialogTextRequest) -> DialogTurnResponse:
        with perf_span("dialog.text.total", has_session=bool(payload.session_id), chars=len(payload.content)):
            context = await self._get_or_create_context(payload.session_id)
            if context.state == "READY_TO_INTERVIEW":
                await self._transition(context, "INTERVIEWING")
            elif context.state != "INTERVIEWING":
                await self._transition(context, "READY_TO_INTERVIEW")
                await self._transition(context, "INTERVIEWING")

            user_content = payload.content.strip()

            assistant_content, _emotion = await self.interview_agent.generate_turn(
                user_message=user_content,
                recent_messages=[],
            )
            context.updated_at = datetime.now(UTC)

        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=self._current_state(context),
            previous_state=context.previous_state,
            action="append_message",
            message=DialogMessage(content=assistant_content),
            cards=[],
            card_group="none",
            guidance_round=context.guidance_round,
            max_guidance_rounds=context.max_guidance_rounds,
            can_continue_guidance=False,
            response_source="llm" if settings.dashscope_api_key else "fallback",
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

    async def get_state(self, session_id: str) -> InterviewStateResponse:
        context = await self._get_or_create_context(session_id)
        return InterviewStateResponse(
            session_id=context.session_id,
            state=self._current_state(context),
        )

    async def get_userinfo(self, user_id: str) -> UserInfoResponse:
        return UserInfoResponse(
            user_id=user_id,
            userinfo=await self._get_userinfo(user_id),
        )

    async def save_userinfo(self, user_id: str, payload: UserInfoRequest) -> UserInfoResponse:
        mapping = {
            key: str(value).strip()
            for key, value in payload.model_dump().items()
            if str(key).strip() and str(value).strip()
        }
        await self._replace_userinfo(user_id, mapping)
        return UserInfoResponse(
            user_id=user_id,
            userinfo=await self._get_userinfo(user_id),
        )

    async def _ready_to_interview(self, context: InterviewContext) -> DialogTurnResponse:
        message = "好的，我们准备开始采访。您可以从一个人、一个地方，或一件小事慢慢说起。"
        await self._transition(context, "READY_TO_INTERVIEW")
        guidance_round = await self._get_guidance_round(context.session_id)
        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=self._current_state(context),
            previous_state=context.previous_state,
            action="ready_to_interview",
            message=DialogMessage(content=message),
            cards=[],
            card_group="none",
            guidance_round=guidance_round,
            max_guidance_rounds=MAX_GUIDANCE_ROUNDS,
            can_continue_guidance=False,
            response_source="none",
        )

    async def _show_guidance_cards(self, context: InterviewContext) -> DialogTurnResponse:
        await self._transition(context, "GUIDANCE_CARD")
        guidance_round = await self._get_guidance_round(context.session_id)
        if guidance_round >= MAX_GUIDANCE_ROUNDS:
            return DialogTurnResponse(
                session_id=context.session_id,
                current_state=self._current_state(context),
                previous_state=context.previous_state,
                action="show_entry_cards",
                message=DialogMessage(content=random.choice(GUIDANCE_LIMIT_MESSAGES)),
                cards=self._cards([ENTRY_CARDS[0]]),
                card_group="entry",
                guidance_round=guidance_round,
                max_guidance_rounds=MAX_GUIDANCE_ROUNDS,
                can_continue_guidance=False,
                response_source="none",
            )

        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=self._current_state(context),
            previous_state=context.previous_state,
            action="show_guidance_cards",
            message=DialogMessage(content="没关系，您可以先选一个最接近现在感受的卡片，我会把接下来的问题调得更轻一点。"),
            cards=self._cards(GUIDANCE_CARDS),
            card_group="guidance",
            guidance_round=guidance_round,
            max_guidance_rounds=MAX_GUIDANCE_ROUNDS,
            can_continue_guidance=True,
            response_source="none",
        )

    async def _handle_guidance_card(
        self,
        context: InterviewContext,
        card_id: str,
        question: str | None = None,
    ) -> DialogTurnResponse:
        guidance_round = await self._get_guidance_round(context.session_id)
        if guidance_round >= MAX_GUIDANCE_ROUNDS:
            await self._transition(context, "GUIDANCE_CARD")
            return DialogTurnResponse(
                session_id=context.session_id,
                current_state=self._current_state(context),
                previous_state=context.previous_state,
                action="append_message",
                message=DialogMessage(content=random.choice(GUIDANCE_LIMIT_MESSAGES)),
                cards=self._cards([ENTRY_CARDS[0]]),
                card_group="entry",
                guidance_round=guidance_round,
                max_guidance_rounds=MAX_GUIDANCE_ROUNDS,
                can_continue_guidance=False,
                response_source="fallback",
            )

        corpus = CARD_RESPONSE_CORPUS.get(card_id) or {
            "card_label": question or "我不了解该如何参加一次采访",
            "response": "不用紧张呀，我们会用轻松聊天的方式慢慢来。",
        }

        generated = await self.llm.generate_guidance_response(
            card_id=card_id,
            card_corpus=corpus,
            fallback_message=corpus["response"],
            question=question,
        )

        await self._transition(context, "GUIDANCE_CARD")
        guidance_round += 1
        await self._set_guidance_round(context.session_id, guidance_round)
        context.updated_at = datetime.now(UTC)

        can_continue = guidance_round < MAX_GUIDANCE_ROUNDS
        return DialogTurnResponse(
            session_id=context.session_id,
            current_state=self._current_state(context),
            previous_state=context.previous_state,
            action="append_message",
            message=DialogMessage(content=generated["assistant_message"]),
            cards=self._cards(ENTRY_CARDS),
            card_group="entry",
            guidance_round=guidance_round,
            max_guidance_rounds=MAX_GUIDANCE_ROUNDS,
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
            state="INIT",
            created_at=now,
            updated_at=now,
        )
        await self._save_state(context)
        return context

    async def _get_context(self, session_id: str) -> InterviewContext | None:
        raw = await self._redis_get(self._key(session_id))
        if raw is None:
            return None
        now = datetime.now(UTC)
        state = self._decode_state(raw)
        context = InterviewContext(
            session_id=session_id,
            state=state,
            created_at=now,
            updated_at=now,
        )
        if raw != state:
            await self._save_state(context)
        return context

    async def _save_state(self, context: InterviewContext) -> None:
        await self._redis_set(self._key(context.session_id), context.state)

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

    async def _redis_hset(self, key: str, mapping: dict[str, str]) -> None:
        for attempt in range(2):
            try:
                await self.redis.hset(key, mapping=mapping)
                await self.redis.expire(key, settings.session_ttl_seconds)
                return
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)

    async def _redis_hgetall(self, key: str) -> dict[str, str]:
        for attempt in range(2):
            try:
                return await self.redis.hgetall(key)
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)
        return {}

    async def _redis_delete(self, key: str) -> None:
        for attempt in range(2):
            try:
                await self.redis.delete(key)
                return
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)

    async def _get_guidance_round(self, session_id: str) -> int:
        raw = await self._redis_get(self._guidance_round_key(session_id))
        if raw is None:
            return 0
        try:
            return max(0, int(raw))
        except ValueError:
            return 0

    async def _set_guidance_round(self, session_id: str, value: int) -> None:
        await self._redis_set(self._guidance_round_key(session_id), str(value))

    async def _transition(self, context: InterviewContext, to_state: InterviewState) -> None:
        if context.state != to_state:
            context.previous_state = self._current_state(context)
            context.state = to_state
        context.updated_at = datetime.now(UTC)
        await self._save_state(context)

    async def _get_userinfo(self, user_id: str) -> dict[str, str]:
        return await self._redis_hgetall(self._userinfo_key(user_id))

    async def _replace_userinfo(self, user_id: str, mapping: dict[str, str]) -> None:
        key = self._userinfo_key(user_id)
        await self._redis_delete(key)
        if mapping:
            await self._redis_hset(key, mapping)

    @staticmethod
    def _decode_state(raw: str) -> str:
        if not raw.startswith("{"):
            return raw if raw in VALID_INTERVIEW_STATES else "INIT"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return "INIT"
        state = data.get("state") or data.get("current_state")
        return state if isinstance(state, str) and state in VALID_INTERVIEW_STATES else "INIT"

    @staticmethod
    def _current_state(context: InterviewContext) -> InterviewState:
        state = context.state if context.state in VALID_INTERVIEW_STATES else "INIT"
        return cast(InterviewState, state)

    @staticmethod
    def _cards(raw_cards: list[dict[str, str]]) -> list[InterviewCard]:
        return [InterviewCard(**card) for card in raw_cards]

    @staticmethod
    def _key(session_id: str) -> str:
        return f"interview:state:{session_id}"

    @staticmethod
    def _userinfo_key(user_id: str) -> str:
        return f"userinfo:{user_id}"

    @staticmethod
    def _guidance_round_key(session_id: str) -> str:
        return f"interview:guidance_round:{session_id}"
