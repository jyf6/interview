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
                    message=DialogMessage(content="采：这次采访已经完成了，感谢您分享这些珍贵的人生故事。"),
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
            progress = self._apply_initial_detected_stage(progress, user_content, history)
            await self._append_message(context.session_id, "user", user_content)
            stage_description = self._stage_description(progress)

            turn = await self.interview_agent.generate_turn(
                user_message=user_content,
                recent_messages=history,
                stage_description=stage_description,
                remaining_rounds=progress["remaining_rounds"],
            )
            assistant_content = turn.reply
            await self._append_message(context.session_id, "assistant", assistant_content)
            progress = self._apply_detected_stage_mention(progress, turn.route, user_content)
            if int(progress.get("awaiting_stage_completion", 0)) and turn.route.route != "extended_interview":
                progress = await self._complete_awaiting_stage_if_needed(context, progress)
            progress = await self._advance_interview_progress(
                context,
                progress,
                round_decrement=turn.route.round_decrement,
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
            response_source=turn.response_source,
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
                "remaining_rounds": int(INTERVIEW_STAGE_BY_ID[FIRST_INTERVIEW_STAGE]["rounds"]),
                "completed": 0,
                "visited_stage_ids": [],
                "pending_stage_ids": [],
                "pending_stage_mentions": {},
                "awaiting_stage_completion": 0,
            },
        )

    async def _get_or_create_interview_progress(self, session_id: str) -> dict[str, Any]:
        raw = await self._redis_get(self._interview_progress_key(session_id))
        if not raw:
            progress = {
                "stage_id": FIRST_INTERVIEW_STAGE,
                "remaining_rounds": int(INTERVIEW_STAGE_BY_ID[FIRST_INTERVIEW_STAGE]["rounds"]),
                "completed": 0,
                "visited_stage_ids": [],
                "pending_stage_ids": [],
                "pending_stage_mentions": {},
                "awaiting_stage_completion": 0,
            }
            await self._set_interview_progress(session_id, progress)
            return progress

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        stage_id = data.get("stage_id") if data.get("stage_id") in INTERVIEW_STAGE_BY_ID else FIRST_INTERVIEW_STAGE
        try:
            remaining_rounds = max(0, int(data.get("remaining_rounds", 0)))
        except (TypeError, ValueError):
            remaining_rounds = int(INTERVIEW_STAGE_BY_ID[stage_id]["rounds"])
        completed = 1 if str(data.get("completed")) == "1" else 0
        visited_stage_ids = self._valid_stage_id_list(data.get("visited_stage_ids"))
        pending_stage_ids = self._valid_stage_id_list(data.get("pending_stage_ids"))
        pending_stage_mentions = self._valid_stage_mentions(data.get("pending_stage_mentions"))
        awaiting_stage_completion = 1 if str(data.get("awaiting_stage_completion")) == "1" else 0
        stage_transition_hint = str(data.get("stage_transition_hint") or "")[:160]
        return {
            "stage_id": stage_id,
            "remaining_rounds": remaining_rounds,
            "completed": completed,
            "visited_stage_ids": visited_stage_ids,
            "pending_stage_ids": pending_stage_ids,
            "pending_stage_mentions": pending_stage_mentions,
            "stage_transition_hint": stage_transition_hint,
            "awaiting_stage_completion": awaiting_stage_completion,
        }

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
                },
                ensure_ascii=False,
            ),
        )

    async def _advance_interview_progress(
        self,
        context: InterviewContext,
        progress: dict[str, Any],
        *,
        round_decrement: int,
    ) -> dict[str, Any]:
        if progress.get("completed"):
            return progress

        if round_decrement:
            progress["remaining_rounds"] = max(0, int(progress["remaining_rounds"]) - 1)
            if int(progress["remaining_rounds"]) <= 0:
                progress["awaiting_stage_completion"] = 1

        await self._set_interview_progress(context.session_id, progress)
        return progress

    async def _complete_awaiting_stage_if_needed(
        self,
        context: InterviewContext,
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        if progress.get("completed") or not int(progress.get("awaiting_stage_completion", 0)):
            return progress

        stage_id = str(progress["stage_id"])
        progress = self._mark_stage_visited(progress, stage_id)
        next_stage_id = self._next_unvisited_stage_id(progress)
        if next_stage_id is None:
            progress["completed"] = 1
            progress["remaining_rounds"] = 0
            progress["awaiting_stage_completion"] = 0
            progress["stage_transition_hint"] = ""
            await self._set_interview_progress(context.session_id, progress)
            await self._transition(context, "end")
            return progress

        progress["stage_id"] = next_stage_id
        progress["remaining_rounds"] = int(INTERVIEW_STAGE_BY_ID[next_stage_id]["rounds"])
        progress["stage_transition_hint"] = InterviewStateMachine._stage_transition_hint_for(progress, next_stage_id)
        progress["awaiting_stage_completion"] = 0
        await self._set_interview_progress(context.session_id, progress)
        return progress

    @staticmethod
    def _apply_initial_detected_stage(
        progress: dict[str, Any],
        user_content: str,
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        has_prior_user_message = any(message.get("role") == "user" for message in history)
        if has_prior_user_message:
            return progress
        detected_stage = InterviewAgentService._detect_stage(user_content)
        return InterviewStateMachine._move_progress_to_initial_stage(progress, detected_stage)

    @staticmethod
    def _apply_detected_stage_mention(progress: dict[str, Any], route: Any, user_content: str = "") -> dict[str, Any]:
        detected_stage = str(getattr(route, "detected_stage", "unclear"))
        current_stage = str(progress.get("stage_id", ""))
        if detected_stage not in INTERVIEW_STAGE_BY_ID or detected_stage == current_stage:
            return progress
        visited = InterviewStateMachine._valid_stage_id_list(progress.get("visited_stage_ids"))
        pending = InterviewStateMachine._valid_stage_id_list(progress.get("pending_stage_ids"))
        mentions = InterviewStateMachine._valid_stage_mentions(progress.get("pending_stage_mentions"))
        if detected_stage in visited or detected_stage in pending:
            return progress
        mention = user_content.strip()[:120]
        if mention:
            mentions[detected_stage] = mention
        return {
            **progress,
            "visited_stage_ids": visited,
            "pending_stage_ids": [*pending, detected_stage],
            "pending_stage_mentions": mentions,
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
        return {
            **progress,
            "stage_id": detected_stage,
            "remaining_rounds": int(INTERVIEW_STAGE_BY_ID[detected_stage]["rounds"]),
            "completed": 0,
            "stage_transition_hint": "",
            "awaiting_stage_completion": 0,
        }

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
        if not mention:
            return ""
        progress["pending_stage_mentions"] = mentions
        stage = INTERVIEW_STAGE_BY_ID.get(next_stage_id, {})
        stage_name = str(stage.get("name", next_stage_id))
        return f"用户上一阶段曾提到与{stage_name}相关的内容：{mention}"

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

    async def _append_message(self, session_id: str, role: str, content: str) -> None:
        message = {
            "role": role,
            "content": content,
            "created_at": datetime.now(UTC).isoformat(),
        }
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
                messages.append({"role": role, "content": content})
        return messages

    @staticmethod
    def _stage_description(progress: dict[str, Any]) -> str:
        stage_id = str(progress["stage_id"])
        stage = INTERVIEW_STAGE_BY_ID.get(stage_id, INTERVIEW_STAGE_BY_ID[FIRST_INTERVIEW_STAGE])
        remaining_rounds = int(progress["remaining_rounds"])
        task = InterviewStateMachine._stage_task(stage_id, remaining_rounds)
        return "\n".join(
            [
                f"阶段：{stage['id']} {stage['name']}",
                f"必须覆盖：{stage['coverage']}",
                f"边界：{stage['boundary']}",
                f"追问策略：{stage['followup']}",
                f"阶段切换衔接：{str(progress.get('stage_transition_hint', '')).strip() or '无'}",
                f"当前阶段建议剩余轮数：{remaining_rounds}",
                task,
            ]
        )

    @staticmethod
    def _stage_task(stage_id: str, remaining_rounds: int) -> str:
        if stage_id == LAST_INTERVIEW_STAGE and remaining_rounds <= 1:
            return FINAL_STAGE_TASK
        normalized_remaining = min(max(remaining_rounds, 1), 4)
        return STAGE_TASK_BY_REMAINING_ROUNDS[normalized_remaining]

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
