import asyncio
import json
import random
from datetime import UTC, datetime
from typing import Any, cast, get_args
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError as RedisResponseError
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
MAIN_QUESTION_IDS = tuple(range(1, 9))
INTERVIEW_STAGES = [
    {
        "id": "S1",
        "rounds": 4,
        "name": "童年时光",
        "coverage": "成长环境、家庭处境、日常生活、难忘事件、家人玩伴、性格影响或心底感触。",
        "boundary": "不追玩具、食物、天气等碎片细节；不过早进入成年事业、婚姻和晚年总结。",
        "followup": "出现可扩展素材时单步扩展；积极性下降时停止扩展支线并回到当前阶段主问题。",
    },
    {
        "id": "S2",
        "rounds": 4,
        "name": "青春岁月",
        "coverage": "求学、离家或初入社会的处境，学习工作主线，关键事件，同伴师长，成长和得失。",
        "boundary": "不追无关琐碎细节；不过早进入中年责任和晚年总结。",
        "followup": "出现可扩展素材时单步扩展；积极性下降时停止扩展支线并回到当前阶段主问题。",
    },
    {
        "id": "S3",
        "rounds": 4,
        "name": "人生转折",
        "coverage": "成家、择业、重大选择、责任、困境低谷、压力来源、支持分担、改变收获和遗憾。",
        "boundary": "追问要温和；遇到回避或沉重内容转向支撑、温暖和后来变化，不深挖痛苦细节。",
        "followup": "出现可扩展素材时单步扩展；积极性下降时停止扩展支线并回到当前阶段主问题。",
    },
    {
        "id": "S4",
        "rounds": 4,
        "name": "岁月阅历",
        "coverage": "当前生活环境和处境，日常节奏，代表性事件，家人老友邻里，心态变化和生活感悟。",
        "boundary": "问题更平和、收拢，不再开启过大的新事件。",
        "followup": "出现可扩展素材时单步扩展；积极性下降时停止扩展支线并回到当前阶段主问题。",
    },
    {
        "id": "S5",
        "rounds": 4,
        "name": "收尾总结",
        "coverage": "整个人生的主线，重要经历或转折，感谢或牵挂的人，人生总结、释怀、遗憾和留给家人的话。",
        "boundary": "不再开启新的阶段性故事。",
        "followup": "出现可扩展素材时围绕总结、感谢、遗憾、释怀单步扩展；积极性下降时温情收尾。",
    },
]
INTERVIEW_STAGE_BY_ID = {stage["id"]: stage for stage in INTERVIEW_STAGES}
FIRST_INTERVIEW_STAGE = INTERVIEW_STAGES[0]["id"]
LAST_INTERVIEW_STAGE = INTERVIEW_STAGES[-1]["id"]
INTERVIEW_STAGE_IDS = [stage["id"] for stage in INTERVIEW_STAGES]
STAGE_STATUS_VALUES = {"not_started", "pending", "active", "completed"}
STAGE_STATUS_ORDER = ("not_started", "pending", "active", "completed")
STAGE_TASK_BY_REMAINING_ROUNDS = {
    4: (
        "本轮采访任务：环境与处境。下一问要覆盖这段时期的生活或工作环境、时代条件、家庭或个人处境，"
        "让用户先给出这段人生阶段的大致背景。"
    ),
    3: (
        "本轮采访任务：日常主线。下一问要覆盖这段时期平日主要做什么、日常节奏和主要生活状态。"
    ),
    2: (
        "本轮采访任务：关键事件。下一问要覆盖这段时期最有代表性的一件大事、转折、高光或困难。"
    ),
    1: (
        "本轮采访任务：人际与心境。下一问要覆盖这段时期身边重要的人、关系变化，"
        "以及这段时光带来的改变、收获、遗憾或整体心境。若用户已经讲清楚这些内容，就简短收束当前阶段并自然引到下一阶段。"
    ),
}
STAGE_SUPPLEMENT_TASK = (
    "本轮采访任务：当前阶段 1-8 号主问题已全部收集完成。"
    "暂不切换阶段，继续调用当前阶段主问题提示词，让模型输出编号 9 的补充询问，"
    "询问用户关于当前阶段还有没有没问到但想补充的内容。"
)
FINAL_STAGE_TASK = (
    "本轮采访任务：最终收尾。用户刚回答了人生总结或心境得失，"
    "下一句要温情感谢并结束采访，不要再提出新的问题。"
)
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
            state_interview=await self._get_or_create_interview_progress(context.session_id),
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
            if context.state == "end":
                progress = await self._get_or_create_interview_progress(context.session_id)
                return DialogTurnResponse(
                    session_id=context.session_id,
                    current_state=self._current_state(context),
                    previous_state=context.previous_state,
                    action="append_message",
                    message=DialogMessage(content="这次采访已经完成了，感谢您分享这些珍贵的人生故事。"),
                    cards=[],
                    card_group="none",
                    guidance_round=context.guidance_round,
                    max_guidance_rounds=context.max_guidance_rounds,
                    can_continue_guidance=False,
                    response_source="none",
                    state_interview=progress,
                )
            if context.state == "READY_TO_INTERVIEW":
                await self._transition(context, "INTERVIEWING")
            elif context.state != "INTERVIEWING":
                await self._transition(context, "READY_TO_INTERVIEW")
                await self._transition(context, "INTERVIEWING")

            user_content = payload.content.strip()
            progress = await self._get_or_create_interview_progress(context.session_id)
            history = await self._get_messages(context.session_id)
            await self._append_message(
                context.session_id,
                "user",
                user_content,
                stage_id=str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE),
            )
            progress = self._mark_active_main_question_answered(progress)
            if progress.get("awaiting_stage_completion") and progress.get("supplement_answered"):
                progress = await self._complete_awaiting_stage_if_needed(context, progress)
            stage_description = self._stage_description(progress)
            stage_detection = await self.interview_agent.detect_user_stage(user_message=user_content)
            progress = self._apply_initial_detected_stage(progress, stage_detection, history)
            await self._assign_latest_user_message_stage(
                context.session_id,
                str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE),
            )
            progress = self._apply_detected_stage_mention(progress, stage_detection, user_content)
            progress = self._set_turn_transition_hint(progress, route_name=None, history=history)
            stage_description = self._stage_description(progress)

            route = await self.interview_agent.judge_turn_route(
                user_message=user_content,
                recent_messages=history,
                stage_description=stage_description,
                remaining_rounds=progress["remaining_rounds"],
            )
            progress = self._set_turn_transition_hint(progress, route_name=route.route, history=history)
            stage_description = self._stage_description(progress)
            stage_history = await self._get_stage_messages(
                context.session_id,
                str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE),
            )
            assistant_content, response_source, main_question_id = await self.interview_agent.generate_reply_for_route(
                route=route,
                user_message=user_content,
                recent_messages=stage_history,
                stage_description=stage_description,
                remaining_rounds=progress["remaining_rounds"],
                completed_main_question_ids=self._valid_main_question_ids(
                    progress.get("completed_main_question_ids")
                ),
            )
            progress = self._set_active_main_question(progress, route.route, main_question_id)
            await self._append_message(
                context.session_id,
                "assistant",
                assistant_content,
                stage_id=str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE),
            )
            progress = await self._advance_interview_progress(context, progress)
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
            response_source=response_source,
            state_interview=progress,
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
            state_interview=await self._get_or_create_interview_progress(context.session_id),
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
        await self._transition(context, "READY_TO_INTERVIEW")
        await self._reset_interview_progress(context.session_id)
        progress = await self._get_or_create_interview_progress(context.session_id)
        icebreaker = await self.interview_agent.generate_icebreaker(
            recent_messages=await self._get_messages(context.session_id),
            stage_description=self._stage_description(progress),
        )
        message = icebreaker.reply
        await self._append_message(context.session_id, "assistant", message)
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
            response_source=icebreaker.response_source,
            state_interview=progress,
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
        await self._overwrite_state_value(self._key(context.session_id), context.state)

    async def _redis_get(self, key: str) -> str | None:
        for attempt in range(2):
            try:
                return await self.redis.get(key)
            except RedisResponseError as exc:
                if "WRONGTYPE" not in str(exc):
                    raise
                await self._redis_delete(key)
                return None
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
            except RedisResponseError as exc:
                if "WRONGTYPE" not in str(exc):
                    raise
                await self._redis_delete(key)
                return {}
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)
        return {}

    async def _redis_rpush(self, key: str, value: str) -> None:
        for attempt in range(2):
            try:
                await self.redis.rpush(key, value)
                await self.redis.expire(key, settings.session_ttl_seconds)
                return
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)

    async def _overwrite_state_value(self, key: str, value: str) -> None:
        """State-machine keys are scalar snapshots, never append-only history."""
        await self._redis_set(key, value)

    async def _redis_lrange(self, key: str, start: int, end: int) -> list[str]:
        for attempt in range(2):
            try:
                return await self.redis.lrange(key, start, end)
            except RedisResponseError as exc:
                if "WRONGTYPE" not in str(exc):
                    raise
                await self._redis_delete(key)
                return []
            except (RedisConnectionError, RedisTimeoutError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.08)
        return []

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
        await self._overwrite_state_value(self._guidance_round_key(session_id), str(value))

    async def _reset_interview_progress(self, session_id: str) -> None:
        await self._redis_delete(self._interview_progress_key(session_id))
        await self._redis_delete(self._messages_key(session_id))
        await self._set_interview_progress(
            session_id,
            {
                "stage_id": FIRST_INTERVIEW_STAGE,
                "remaining_rounds": len(MAIN_QUESTION_IDS),
                "completed": 0,
                "visited_stage_ids": [],
                "pending_stage_ids": [],
                "pending_stage_mentions": {},
                "awaiting_stage_completion": 0,
                "completed_main_question_ids": [],
                "active_main_question_id": None,
                "supplement_answered": 0,
                "started_stage_id": None,
                "stage_flow": [],
                "stage_statuses": self._initial_stage_statuses(FIRST_INTERVIEW_STAGE),
                "stage_plan": self._stage_plan(self._initial_stage_statuses(FIRST_INTERVIEW_STAGE), {}),
            },
        )

    async def _get_or_create_interview_progress(self, session_id: str) -> dict[str, Any]:
        raw = await self._redis_get(self._interview_progress_key(session_id))
        if not raw:
            progress = {
                "stage_id": FIRST_INTERVIEW_STAGE,
                "remaining_rounds": len(MAIN_QUESTION_IDS),
                "completed": 0,
                "visited_stage_ids": [],
                "pending_stage_ids": [],
                "pending_stage_mentions": {},
                "awaiting_stage_completion": 0,
                "completed_main_question_ids": [],
                "active_main_question_id": None,
                "supplement_answered": 0,
                "started_stage_id": None,
                "stage_flow": [],
                "stage_statuses": self._initial_stage_statuses(FIRST_INTERVIEW_STAGE),
                "stage_plan": self._stage_plan(self._initial_stage_statuses(FIRST_INTERVIEW_STAGE), {}),
            }
            await self._set_interview_progress(session_id, progress)
            return self._hydrate_progress_view(progress)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        stage_id = data.get("stage_id") if data.get("stage_id") in INTERVIEW_STAGE_BY_ID else FIRST_INTERVIEW_STAGE
        try:
            remaining_rounds = max(0, int(data.get("remaining_rounds", 0)))
        except (TypeError, ValueError):
            remaining_rounds = len(MAIN_QUESTION_IDS)
        completed = 1 if str(data.get("completed")) == "1" else 0
        visited_stage_ids = self._valid_stage_id_list(data.get("visited_stage_ids"))
        pending_stage_ids = self._valid_stage_id_list(data.get("pending_stage_ids"))
        pending_stage_mentions = self._valid_stage_mentions(data.get("pending_stage_mentions"))
        awaiting_stage_completion = 1 if str(data.get("awaiting_stage_completion")) == "1" else 0
        stage_transition_hint = str(data.get("stage_transition_hint") or "")[:160]
        completed_main_question_ids = self._valid_main_question_ids(data.get("completed_main_question_ids"))
        active_main_question_id = self._valid_main_question_id(data.get("active_main_question_id"))
        supplement_answered = 1 if str(data.get("supplement_answered")) == "1" else 0
        started_stage_id = data.get("started_stage_id") if data.get("started_stage_id") in INTERVIEW_STAGE_BY_ID else None
        stage_flow = self._valid_stage_flow(data.get("stage_flow"))
        stage_statuses = self._valid_stage_statuses(
            data.get("stage_statuses"),
            stage_id,
            visited_stage_ids,
            pending_stage_ids,
        )
        if not completed:
            remaining_rounds = max(0, len(MAIN_QUESTION_IDS) - len(completed_main_question_ids))
            awaiting_stage_completion = 1 if remaining_rounds == 0 else 0
        completed_stage_ids = self._completed_stage_ids(stage_statuses)
        return self._hydrate_progress_view({
            "stage_id": stage_id,
            "stage_name": str(INTERVIEW_STAGE_BY_ID[stage_id]["name"]),
            "stage_order": INTERVIEW_STAGE_IDS.index(stage_id) + 1,
            "remaining_rounds": remaining_rounds,
            "completed": completed,
            "visited_stage_ids": visited_stage_ids,
            "completed_stage_ids": completed_stage_ids,
            "pending_stage_ids": pending_stage_ids,
            "pending_stage_mentions": pending_stage_mentions,
            "stage_transition_hint": stage_transition_hint,
            "awaiting_stage_completion": awaiting_stage_completion,
            "completed_main_question_ids": completed_main_question_ids,
            "active_main_question_id": active_main_question_id,
            "supplement_answered": supplement_answered,
            "started_stage_id": started_stage_id,
            "started_stage_name": self._stage_name(started_stage_id),
            "started_stage_order": self._stage_order(started_stage_id),
            "stage_flow": stage_flow,
            "stage_statuses": stage_statuses,
            "stage_plan": self._stage_plan(stage_statuses, data),
        })

    async def _set_interview_progress(self, session_id: str, progress: dict[str, Any]) -> None:
        await self._overwrite_state_value(
            self._interview_progress_key(session_id),
            json.dumps(
                {
                    "stage_id": str(progress["stage_id"]),
                    "remaining_rounds": int(progress["remaining_rounds"]),
                    "completed": int(progress.get("completed", 0)),
                    "visited_stage_ids": self._valid_stage_id_list(progress.get("visited_stage_ids")),
                    "pending_stage_ids": self._valid_stage_id_list(progress.get("pending_stage_ids")),
                    "pending_stage_mentions": self._valid_stage_mentions(progress.get("pending_stage_mentions")),
                    "stage_transition_hint": str(progress.get("stage_transition_hint", ""))[:160],
                    "awaiting_stage_completion": int(progress.get("awaiting_stage_completion", 0)),
                    "completed_main_question_ids": self._valid_main_question_ids(
                        progress.get("completed_main_question_ids")
                    ),
                    "active_main_question_id": self._valid_main_question_id(progress.get("active_main_question_id")),
                    "supplement_answered": int(progress.get("supplement_answered", 0)),
                    "started_stage_id": progress.get("started_stage_id")
                    if progress.get("started_stage_id") in INTERVIEW_STAGE_BY_ID
                    else None,
                    "stage_flow": self._valid_stage_flow(progress.get("stage_flow")),
                    "stage_statuses": self._valid_stage_statuses(
                        progress.get("stage_statuses"),
                        str(progress["stage_id"]),
                        self._valid_stage_id_list(progress.get("visited_stage_ids")),
                        self._valid_stage_id_list(progress.get("pending_stage_ids")),
                    ),
                    "stage_plan": self._stage_plan(
                        self._valid_stage_statuses(
                            progress.get("stage_statuses"),
                            str(progress["stage_id"]),
                            self._valid_stage_id_list(progress.get("visited_stage_ids")),
                            self._valid_stage_id_list(progress.get("pending_stage_ids")),
                        ),
                        progress,
                    ),
                },
                ensure_ascii=False,
            ),
        )

    async def _advance_interview_progress(
        self,
        context: InterviewContext,
        progress: dict[str, Any],
        *,
        round_decrement: int = 0,
    ) -> dict[str, Any]:
        if not progress.get("completed"):
            completed_ids = self._valid_main_question_ids(progress.get("completed_main_question_ids"))
            remaining_count = max(0, len(MAIN_QUESTION_IDS) - len(completed_ids))
            progress["remaining_rounds"] = remaining_count
            progress["awaiting_stage_completion"] = 1 if remaining_count == 0 else 0
            progress = self._sync_stage_flow(progress)
        await self._set_interview_progress(context.session_id, progress)
        return self._hydrate_progress_view(progress)

    async def _complete_awaiting_stage_if_needed(
        self,
        context: InterviewContext,
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        progress = self._sync_main_question_progress(progress)
        if progress.get("awaiting_stage_completion") and progress.get("supplement_answered"):
            current_stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
            progress = self._mark_stage_visited(progress, current_stage_id)
            progress = self._sync_stage_flow(progress, event="complete", event_stage_id=current_stage_id)
            next_stage_id = self._next_unvisited_stage_id(progress)
            if next_stage_id:
                transition_hint = self._stage_transition_hint_for(progress, next_stage_id)
                pending_stage_ids = [
                    stage_id
                    for stage_id in self._valid_stage_id_list(progress.get("pending_stage_ids"))
                    if stage_id != next_stage_id
                ]
                progress = {
                    **progress,
                    "stage_id": next_stage_id,
                    "remaining_rounds": len(MAIN_QUESTION_IDS),
                    "completed": 0,
                    "pending_stage_ids": pending_stage_ids,
                    "stage_transition_hint": transition_hint,
                    "awaiting_stage_completion": 0,
                    "completed_main_question_ids": [],
                    "active_main_question_id": None,
                    "supplement_answered": 0,
                    "stage_flow": self._stage_flow_without_active(progress.get("stage_flow")),
                }
                progress = self._sync_stage_flow(progress)
            else:
                progress = {
                    **progress,
                    "completed": 1,
                    "awaiting_stage_completion": 0,
                    "active_main_question_id": None,
                    "supplement_answered": 0,
                }
                progress = self._sync_stage_flow(progress, event="complete", event_stage_id=current_stage_id)
        progress = self._sync_stage_flow(progress)
        await self._set_interview_progress(context.session_id, progress)
        return self._hydrate_progress_view(progress)

    async def _complete_stage_if_needed(
        self,
        context: InterviewContext,
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._complete_awaiting_stage_if_needed(context, progress)

    @staticmethod
    def _apply_initial_detected_stage(
        progress: dict[str, Any],
        stage_detection: Any,
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        has_prior_user_message = any(message.get("role") == "user" for message in history)
        if has_prior_user_message:
            return progress
        detected_stage = str(getattr(stage_detection, "stage_code", "unclear"))
        if detected_stage not in INTERVIEW_STAGE_BY_ID:
            return InterviewStateMachine._sync_stage_flow(progress, event="start")
        return InterviewStateMachine._move_progress_to_initial_stage(progress, detected_stage)

    @staticmethod
    def _apply_detected_stage_mention(
        progress: dict[str, Any],
        stage_detection: Any,
        user_content: str = "",
    ) -> dict[str, Any]:
        detected_stage = str(getattr(stage_detection, "stage_code", "unclear"))
        current_stage = str(progress.get("stage_id", ""))
        if detected_stage not in INTERVIEW_STAGE_BY_ID or detected_stage == current_stage:
            return progress
        visited = InterviewStateMachine._valid_stage_id_list(progress.get("visited_stage_ids"))
        pending = InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids"))
        mentions = InterviewStateMachine._valid_stage_mentions(progress.get("pending_stage_mentions"))
        statuses = InterviewStateMachine._valid_stage_statuses(
            progress.get("stage_statuses"),
            current_stage,
            visited,
            pending,
        )
        if detected_stage in visited or detected_stage in pending or statuses.get(detected_stage) == "completed":
            return progress
        mention = user_content.strip()[:120]
        if mention:
            mentions[detected_stage] = mention
        return {
            **progress,
            "visited_stage_ids": visited,
            "pending_stage_ids": [*pending, detected_stage],
            "pending_stage_mentions": mentions,
            "stage_statuses": InterviewStateMachine._valid_stage_statuses(
                progress.get("stage_statuses"),
                current_stage,
                visited,
                [*pending, detected_stage],
            ),
        }

    @staticmethod
    def _apply_route_stage_shift(progress: dict[str, Any], route: Any) -> dict[str, Any]:
        return progress

    @staticmethod
    def _route_requests_next_stage(route: Any) -> bool:
        return False

    @staticmethod
    def _move_progress_to_initial_stage(progress: dict[str, Any], detected_stage: str) -> dict[str, Any]:
        if detected_stage not in INTERVIEW_STAGE_BY_ID:
            return progress
        updated = {
            **progress,
            "stage_id": detected_stage,
            "remaining_rounds": len(MAIN_QUESTION_IDS),
            "completed": 0,
            "stage_transition_hint": "",
            "awaiting_stage_completion": 0,
            "completed_main_question_ids": [],
            "active_main_question_id": None,
            "supplement_answered": 0,
            "stage_flow": InterviewStateMachine._stage_flow_without_active(progress.get("stage_flow")),
        }
        return InterviewStateMachine._sync_stage_flow(updated, event="start")

    @staticmethod
    def _mark_stage_visited(progress: dict[str, Any], stage_id: str) -> dict[str, Any]:
        visited = InterviewStateMachine._valid_stage_id_list(progress.get("visited_stage_ids"))
        if stage_id in INTERVIEW_STAGE_BY_ID and stage_id not in visited:
            visited = [*visited, stage_id]
        pending = [
            pending_stage
            for pending_stage in InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids"))
            if pending_stage != stage_id
        ]
        mentions = InterviewStateMachine._valid_stage_mentions(progress.get("pending_stage_mentions"))
        mentions.pop(stage_id, None)
        return {**progress, "visited_stage_ids": visited, "pending_stage_ids": pending, "pending_stage_mentions": mentions}

    @staticmethod
    def _next_unvisited_stage_id(progress: dict[str, Any]) -> str | None:
        visited = set(InterviewStateMachine._valid_stage_id_list(progress.get("visited_stage_ids")))
        statuses = InterviewStateMachine._valid_stage_statuses(
            progress.get("stage_statuses"),
            str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE),
            list(visited),
            InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids")),
        )
        visited.update(stage_id for stage_id, status in statuses.items() if status == "completed")
        pending = InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids"))
        for stage_id in pending:
            if stage_id not in visited:
                return stage_id
        for stage_id in INTERVIEW_STAGE_IDS:
            if stage_id not in visited:
                return stage_id
        return None

    @staticmethod
    def _stage_transition_hint_for(progress: dict[str, Any], next_stage_id: str) -> str:
        mentions = InterviewStateMachine._valid_stage_mentions(progress.get("pending_stage_mentions"))
        mention = mentions.pop(next_stage_id, "")
        progress["pending_stage_mentions"] = mentions
        stage = INTERVIEW_STAGE_BY_ID.get(next_stage_id, {})
        stage_name = str(stage.get("name", next_stage_id))
        if not mention:
            return f"上一阶段已完成，代码状态机按计划进入{stage_name}；请柔和开启新阶段主问题。"
        return f"用户上一阶段曾提到与{stage_name}相关的内容：{mention}"

    @staticmethod
    def _set_turn_transition_hint(
        progress: dict[str, Any],
        *,
        route_name: str | None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
        stage_name = InterviewStateMachine._stage_name(stage_id) or stage_id
        has_prior_user_message = any(message.get("role") == "user" for message in history or [])
        existing_hint = str(progress.get("stage_transition_hint") or "").strip()
        has_stage_switch_hint = existing_hint.startswith("用户上一阶段曾提到") or existing_hint.startswith("上一阶段已完成")

        if not has_prior_user_message:
            started_stage_id = progress.get("started_stage_id")
            route_text = {
                "normal_interview": "本轮路由为主问题推进",
                "extended_interview": "本轮路由为扩展追问",
                "emotional_guidance": "本轮路由已归一化为主问题推进",
            }.get(route_name or "", "正式采访即将开始")
            if started_stage_id == stage_id:
                hint = f"这是正式采访开始，用户第一段回答指向{stage_name}，{route_text}；请先自然接住，再按当前阶段推进。"
            else:
                hint = f"这是正式采访开始，代码状态机当前从{stage_name}阶段启动，{route_text}；请自然承接用户第一段回答。"
        elif route_name is None and has_stage_switch_hint:
            hint = existing_hint
        elif route_name == "extended_interview":
            prefix = f"当前进入{stage_name}阶段，{existing_hint}；" if has_stage_switch_hint else f"当前仍在{stage_name}阶段，"
            hint = f"{prefix}本轮路由为扩展追问；请承接用户刚提供的素材，只做一次单步追问。"
        elif route_name == "normal_interview":
            prefix = f"当前进入{stage_name}阶段，{existing_hint}；" if has_stage_switch_hint else f"当前仍在{stage_name}阶段，"
            hint = f"{prefix}本轮路由为主问题推进；请承接用户上一轮回答并继续当前阶段任务。"
        else:
            hint = f"当前处于{stage_name}阶段，代码状态机未触发阶段跳转；请承接用户回答并保持在当前阶段。"

        return {**progress, "stage_transition_hint": hint[:160]}

    @staticmethod
    def _valid_stage_id_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            stage_id = str(item)
            if stage_id in INTERVIEW_STAGE_BY_ID and stage_id not in result:
                result.append(stage_id)
        return result

    @staticmethod
    def _valid_stage_mentions(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, str] = {}
        for key, mention in value.items():
            stage_id = str(key)
            if stage_id in INTERVIEW_STAGE_BY_ID and isinstance(mention, str) and mention.strip():
                result[stage_id] = mention.strip()[:160]
        return result

    @staticmethod
    def _initial_stage_statuses(active_stage_id: str) -> dict[str, str]:
        return {
            stage_id: "active" if stage_id == active_stage_id else "not_started"
            for stage_id in INTERVIEW_STAGE_IDS
        }

    @staticmethod
    def _valid_stage_statuses(
        value: Any,
        current_stage_id: str,
        visited_stage_ids: list[str],
        pending_stage_ids: list[str],
    ) -> dict[str, str]:
        statuses: dict[str, str] = {stage_id: "not_started" for stage_id in INTERVIEW_STAGE_IDS}
        if isinstance(value, dict):
            for key, raw_status in value.items():
                stage_id = str(key)
                status = str(raw_status)
                if stage_id in INTERVIEW_STAGE_BY_ID and status in STAGE_STATUS_VALUES:
                    statuses[stage_id] = status
        for stage_id in visited_stage_ids:
            statuses[stage_id] = "completed"
        for stage_id in pending_stage_ids:
            if statuses.get(stage_id) != "completed":
                statuses[stage_id] = "pending"
        for stage_id, status in list(statuses.items()):
            if status == "active" and stage_id != current_stage_id:
                statuses[stage_id] = "not_started"
        if current_stage_id in INTERVIEW_STAGE_BY_ID:
            if statuses.get(current_stage_id) != "completed":
                statuses[current_stage_id] = "active"
            if current_stage_id in pending_stage_ids:
                statuses[current_stage_id] = "active"
        return statuses

    @staticmethod
    def _valid_stage_flow(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            stage_id = str(item.get("stage_id") or "")
            if stage_id not in INTERVIEW_STAGE_BY_ID:
                continue
            status = str(item.get("status") or "active")
            if status not in STAGE_STATUS_VALUES:
                status = "active"
            entry: dict[str, Any] = {
                "stage_id": stage_id,
                "stage_name": str(INTERVIEW_STAGE_BY_ID[stage_id]["name"]),
                "status": status,
            }
            started_by = str(item.get("started_by") or "").strip()
            if started_by:
                entry["started_by"] = started_by[:40]
            completed_ids = InterviewStateMachine._valid_main_question_ids(item.get("completed_main_question_ids"))
            if completed_ids:
                entry["completed_main_question_ids"] = completed_ids
            entered_at = str(item.get("entered_at") or "").strip()
            if entered_at:
                entry["entered_at"] = entered_at
            completed_at = str(item.get("completed_at") or "").strip()
            if completed_at:
                entry["completed_at"] = completed_at
            result.append(entry)
        return result

    @staticmethod
    def _stage_flow_without_active(value: Any) -> list[dict[str, Any]]:
        return [
            item
            for item in InterviewStateMachine._valid_stage_flow(value)
            if item.get("status") != "active"
        ]

    @staticmethod
    def _hydrate_progress_view(progress: dict[str, Any]) -> dict[str, Any]:
        stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            stage_id = FIRST_INTERVIEW_STAGE
        visited = InterviewStateMachine._valid_stage_id_list(progress.get("visited_stage_ids"))
        pending = InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids"))
        statuses = InterviewStateMachine._valid_stage_statuses(
            progress.get("stage_statuses"),
            stage_id,
            visited,
            pending,
        )
        started_stage_id = progress.get("started_stage_id")
        return {
            **progress,
            "stage_id": stage_id,
            "stage_name": str(INTERVIEW_STAGE_BY_ID[stage_id]["name"]),
            "stage_order": INTERVIEW_STAGE_IDS.index(stage_id) + 1,
            "visited_stage_ids": visited,
            "completed_stage_ids": InterviewStateMachine._completed_stage_ids(statuses),
            "pending_stage_ids": pending,
            "started_stage_id": started_stage_id if started_stage_id in INTERVIEW_STAGE_BY_ID else None,
            "started_stage_name": InterviewStateMachine._stage_name(started_stage_id),
            "started_stage_order": InterviewStateMachine._stage_order(started_stage_id),
            "stage_flow": InterviewStateMachine._valid_stage_flow(progress.get("stage_flow")),
            "stage_statuses": statuses,
            "stage_plan": InterviewStateMachine._stage_plan(statuses, progress),
        }

    @staticmethod
    def _sync_stage_flow(
        progress: dict[str, Any],
        *,
        event: str = "enter",
        event_stage_id: str | None = None,
    ) -> dict[str, Any]:
        current_stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
        visited = InterviewStateMachine._valid_stage_id_list(progress.get("visited_stage_ids"))
        pending = InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids"))
        statuses = InterviewStateMachine._valid_stage_statuses(
            progress.get("stage_statuses"),
            current_stage_id,
            visited,
            pending,
        )
        flow = InterviewStateMachine._valid_stage_flow(progress.get("stage_flow"))
        started_stage_id = progress.get("started_stage_id")
        if started_stage_id not in INTERVIEW_STAGE_BY_ID:
            started_stage_id = current_stage_id if current_stage_id in INTERVIEW_STAGE_BY_ID else None

        target_stage_id = event_stage_id or current_stage_id
        if event == "complete" and target_stage_id in INTERVIEW_STAGE_BY_ID:
            statuses[target_stage_id] = "completed"
            flow = InterviewStateMachine._upsert_stage_flow_entry(
                flow,
                target_stage_id,
                "completed",
                progress,
            )
        just_completed_current_stage = event == "complete" and target_stage_id == current_stage_id
        if current_stage_id in INTERVIEW_STAGE_BY_ID and not progress.get("completed") and not just_completed_current_stage:
            statuses[current_stage_id] = "active"
            flow = InterviewStateMachine._upsert_stage_flow_entry(
                flow,
                current_stage_id,
                "active",
                progress,
                started_by="initial" if event == "start" else "state_machine",
            )
        statuses = InterviewStateMachine._valid_stage_statuses(statuses, current_stage_id, visited, pending)
        return {
            **progress,
            "started_stage_id": started_stage_id,
            "started_stage_name": InterviewStateMachine._stage_name(started_stage_id),
            "started_stage_order": InterviewStateMachine._stage_order(started_stage_id),
            "completed_stage_ids": InterviewStateMachine._completed_stage_ids(statuses),
            "stage_flow": flow,
            "stage_statuses": statuses,
            "stage_plan": InterviewStateMachine._stage_plan(statuses, progress),
        }

    @staticmethod
    def _upsert_stage_flow_entry(
        flow: list[dict[str, Any]],
        stage_id: str,
        status: str,
        progress: dict[str, Any],
        *,
        started_by: str | None = None,
    ) -> list[dict[str, Any]]:
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            return flow
        existing_index = next((index for index, item in enumerate(flow) if item.get("stage_id") == stage_id), None)
        entry = {
            "stage_id": stage_id,
            "stage_name": str(INTERVIEW_STAGE_BY_ID[stage_id]["name"]),
            "status": status,
            "completed_main_question_ids": InterviewStateMachine._valid_main_question_ids(
                progress.get("completed_main_question_ids")
            ),
        }
        if started_by:
            entry["started_by"] = started_by
        if existing_index is None:
            entry["entered_at"] = datetime.now(UTC).isoformat()
        else:
            existing = flow[existing_index]
            if existing.get("entered_at"):
                entry["entered_at"] = existing["entered_at"]
            if existing.get("started_by") and not started_by:
                entry["started_by"] = existing["started_by"]
        if status == "completed":
            existing_completed_at = (
                flow[existing_index].get("completed_at")
                if existing_index is not None and isinstance(flow[existing_index], dict)
                else None
            )
            entry["completed_at"] = existing_completed_at or datetime.now(UTC).isoformat()
        if existing_index is None:
            return [*flow, entry]
        updated = [*flow]
        updated[existing_index] = {**updated[existing_index], **entry}
        return updated

    @staticmethod
    def _completed_stage_ids(stage_statuses: dict[str, str]) -> list[str]:
        return [stage_id for stage_id in INTERVIEW_STAGE_IDS if stage_statuses.get(stage_id) == "completed"]

    @staticmethod
    def _stage_name(stage_id: Any) -> str | None:
        stage = INTERVIEW_STAGE_BY_ID.get(str(stage_id))
        return str(stage["name"]) if stage else None

    @staticmethod
    def _stage_order(stage_id: Any) -> int | None:
        stage_id_str = str(stage_id)
        if stage_id_str not in INTERVIEW_STAGE_BY_ID:
            return None
        return INTERVIEW_STAGE_IDS.index(stage_id_str) + 1

    @staticmethod
    def _stage_plan(stage_statuses: dict[str, str], progress: dict[str, Any]) -> list[dict[str, Any]]:
        current_stage_id = str(progress.get("stage_id") or "")
        pending_mentions = InterviewStateMachine._valid_stage_mentions(progress.get("pending_stage_mentions"))
        plan: list[dict[str, Any]] = []
        for index, stage_id in enumerate(INTERVIEW_STAGE_IDS, start=1):
            item: dict[str, Any] = {
                "stage_id": stage_id,
                "stage_name": str(INTERVIEW_STAGE_BY_ID[stage_id]["name"]),
                "order": index,
                "status": stage_statuses.get(stage_id, "not_started"),
                "is_current": stage_id == current_stage_id,
            }
            if stage_id in pending_mentions:
                item["mentioned_context"] = pending_mentions[stage_id]
            plan.append(item)
        return plan

    @staticmethod
    def _valid_main_question_id(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            question_id = int(value)
        except (TypeError, ValueError):
            return None
        if question_id in MAIN_QUESTION_IDS or question_id == 9:
            return question_id
        return None

    @staticmethod
    def _valid_main_question_ids(value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        result: list[int] = []
        for item in value:
            question_id = InterviewStateMachine._valid_main_question_id(item)
            if question_id in MAIN_QUESTION_IDS and question_id not in result:
                result.append(question_id)
        return result

    @staticmethod
    def _sync_main_question_progress(progress: dict[str, Any]) -> dict[str, Any]:
        completed_ids = InterviewStateMachine._valid_main_question_ids(progress.get("completed_main_question_ids"))
        remaining_count = max(0, len(MAIN_QUESTION_IDS) - len(completed_ids))
        return {
            **progress,
            "completed_main_question_ids": completed_ids,
            "remaining_rounds": remaining_count,
            "awaiting_stage_completion": 1 if remaining_count == 0 and not progress.get("completed") else 0,
        }

    @staticmethod
    def _mark_active_main_question_answered(progress: dict[str, Any]) -> dict[str, Any]:
        active_question_id = InterviewStateMachine._valid_main_question_id(progress.get("active_main_question_id"))
        completed_ids = InterviewStateMachine._valid_main_question_ids(progress.get("completed_main_question_ids"))
        supplement_answered = int(progress.get("supplement_answered", 0))
        if active_question_id == 9:
            supplement_answered = 1
        elif active_question_id is not None and active_question_id not in completed_ids:
            completed_ids.append(active_question_id)
        updated = {
            **progress,
            "completed_main_question_ids": completed_ids,
            "active_main_question_id": None,
            "supplement_answered": supplement_answered,
        }
        return InterviewStateMachine._sync_main_question_progress(updated)

    @staticmethod
    def _stage_main_questions_completed(progress: dict[str, Any]) -> bool:
        completed_ids = set(InterviewStateMachine._valid_main_question_ids(progress.get("completed_main_question_ids")))
        return set(MAIN_QUESTION_IDS).issubset(completed_ids)

    @staticmethod
    def _set_active_main_question(
        progress: dict[str, Any],
        route_name: str,
        main_question_id: Any,
    ) -> dict[str, Any]:
        if route_name != "normal_interview":
            return {**progress, "active_main_question_id": None}
        question_id = InterviewStateMachine._valid_main_question_id(main_question_id)
        if question_id == 9 and int(progress.get("awaiting_stage_completion", 0)):
            return {**progress, "active_main_question_id": question_id}
        if question_id == 9:
            question_id = None
        return {**progress, "active_main_question_id": question_id}

    async def _append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        stage_id: str | None = None,
    ) -> None:
        message = {
            "role": role,
            "content": content,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if stage_id in INTERVIEW_STAGE_BY_ID:
            message["stage_id"] = stage_id
        await self._redis_rpush(self._messages_key(session_id), json.dumps(message, ensure_ascii=False))

    async def _get_messages(self, session_id: str) -> list[dict[str, str]]:
        raw_messages = await self._redis_lrange(self._messages_key(session_id), 0, -1)
        messages: list[dict[str, str]] = []
        for item in raw_messages:
            try:
                data = json.loads(item)
            except json.JSONDecodeError:
                continue
            role = data.get("role")
            content = data.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                message = {"role": role, "content": content}
                stage_id = data.get("stage_id")
                if stage_id in INTERVIEW_STAGE_BY_ID:
                    message["stage_id"] = stage_id
                messages.append(message)
        return messages

    async def _get_stage_messages(self, session_id: str, stage_id: str) -> list[dict[str, str]]:
        messages = await self._get_messages(session_id)
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            return messages
        scoped = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
            if message.get("stage_id") == stage_id
        ]
        if scoped:
            return scoped
        return [
            {"role": message["role"], "content": message["content"]}
            for message in messages
            if "stage_id" not in message
        ]

    async def _assign_latest_user_message_stage(self, session_id: str, stage_id: str) -> None:
        if stage_id not in INTERVIEW_STAGE_BY_ID:
            return
        raw_messages = await self._redis_lrange(self._messages_key(session_id), 0, -1)
        if not raw_messages:
            return
        decoded: list[dict[str, Any]] = []
        latest_user_index: int | None = None
        for index, item in enumerate(raw_messages):
            try:
                message = json.loads(item)
            except json.JSONDecodeError:
                decoded.append({})
                continue
            decoded.append(message if isinstance(message, dict) else {})
            if message.get("role") == "user":
                latest_user_index = index
        if latest_user_index is None:
            return
        decoded[latest_user_index]["stage_id"] = stage_id
        await self._redis_delete(self._messages_key(session_id))
        for message in decoded:
            if message:
                await self._redis_rpush(self._messages_key(session_id), json.dumps(message, ensure_ascii=False))

    @staticmethod
    def _stage_description(progress: dict[str, Any]) -> str:
        stage_id = str(progress["stage_id"])
        stage = INTERVIEW_STAGE_BY_ID.get(stage_id, INTERVIEW_STAGE_BY_ID[FIRST_INTERVIEW_STAGE])
        completed_ids = InterviewStateMachine._valid_main_question_ids(progress.get("completed_main_question_ids"))
        pending_ids = [question_id for question_id in MAIN_QUESTION_IDS if question_id not in completed_ids]
        remaining_rounds = len(pending_ids)
        task = InterviewStateMachine._stage_task(stage_id, remaining_rounds)
        transition_hint = InterviewStateMachine._transition_hint_for_description(progress)
        return "\n".join(
            [
                f"阶段：{stage['id']} {stage['name']}",
                f"必须覆盖：{stage['coverage']}",
                f"边界：{stage['boundary']}",
                f"追问策略：{stage['followup']}",
                f"流程衔接说明：{transition_hint}",
                f"阶段切换衔接：{transition_hint}",
                f"当前阶段建议剩余轮数：{remaining_rounds}",
                f"当前阶段已收集主问题编号：{InterviewStateMachine._format_main_question_ids(completed_ids)}",
                f"当前阶段待收集主问题编号：{InterviewStateMachine._format_main_question_ids(pending_ids)}",
                f"当前阶段剩余主问题数量：{remaining_rounds}",
                task,
            ]
        )

    @staticmethod
    def _transition_hint_for_description(progress: dict[str, Any]) -> str:
        existing_hint = str(progress.get("stage_transition_hint") or "").strip()
        if existing_hint:
            return existing_hint[:160]
        stage_id = str(progress.get("stage_id") or FIRST_INTERVIEW_STAGE)
        stage_name = InterviewStateMachine._stage_name(stage_id) or stage_id
        return f"当前处于{stage_name}阶段，代码状态机未触发阶段跳转；请承接用户回答并保持在当前阶段。"

    @staticmethod
    def _stage_task(stage_id: str, remaining_rounds: int) -> str:
        if remaining_rounds == 0:
            return STAGE_SUPPLEMENT_TASK
        if stage_id == LAST_INTERVIEW_STAGE and remaining_rounds <= 1:
            return FINAL_STAGE_TASK
        if remaining_rounds > 4:
            return (
                "本轮采访任务：由当前阶段主问题提示词在 1-8 号主问题中选择一个尚未收集的编号提问，"
                "并在 JSON 中输出本轮提问的问题编号。"
            )
        normalized_remaining = min(max(remaining_rounds, 1), 4)
        return STAGE_TASK_BY_REMAINING_ROUNDS[normalized_remaining]

    @staticmethod
    def _format_main_question_ids(question_ids: list[int]) -> str:
        ids = InterviewStateMachine._valid_main_question_ids(question_ids)
        return "无" if not ids else "、".join(str(question_id) for question_id in ids)

    @staticmethod
    def _next_stage_id(stage_id: str) -> str | None:
        ids = [stage["id"] for stage in INTERVIEW_STAGES]
        try:
            index = ids.index(stage_id)
        except ValueError:
            return FIRST_INTERVIEW_STAGE
        next_index = index + 1
        return ids[next_index] if next_index < len(ids) else None

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

    @staticmethod
    def _interview_progress_key(session_id: str) -> str:
        return f"interview:state_interview:{session_id}"

    @staticmethod
    def _messages_key(session_id: str) -> str:
        return f"interview:messages:{session_id}"
