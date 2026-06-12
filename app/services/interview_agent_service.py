import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.llm_client import interview_llm
from app.core.perf import perf_span

logger = logging.getLogger(__name__)

SKILL_REFERENCES_DIR = (
    Path(__file__).resolve().parents[2]
    / ".codex"
    / "skills"
    / "interview-prompt-router-zh"
    / "references"
)

ICEBREAKER_FALLBACK = (
    "采：您好，今天想陪您慢慢聊聊过往的人生故事，咱们就像唠家常一样，"
    "不用准备，也不用讲得多完整。最先想起的，是哪一段日子呢？"
)
INTERVIEW_FALLBACK = "采：我已经记下来了。您愿意再多说一点当时的情景吗？"

RouteName = Literal[
    "normal_interview",
    "mild_emotional_guidance",
    "strong_emotional_guidance",
    "resistance_turn",
    "implicit_low_engagement",
]


class InterviewRouteResult(BaseModel):
    route: RouteName = "normal_interview"
    emotion_type: str = "none"
    confidence: float = 0.0
    reason: str = ""
    should_change_topic: bool = False
    do_not_probe_current_topic: bool = False
    round_decrement: int = Field(default=1, ge=0, le=1)


class InterviewTurnResult(BaseModel):
    reply: str
    route: InterviewRouteResult
    response_source: Literal["llm", "fallback"] = "fallback"


class InterviewOpeningResult(BaseModel):
    reply: str
    response_source: Literal["llm", "fallback"] = "fallback"


class InterviewAgentService:
    async def generate_icebreaker(
        self,
        *,
        recent_messages: list[dict[str, str]],
        stage_description: str,
    ) -> InterviewOpeningResult:
        with perf_span("interview.icebreaker.total", history=len(recent_messages)):
            if not settings.dashscope_api_key:
                return InterviewOpeningResult(reply=ICEBREAKER_FALLBACK, response_source="fallback")

            prompt = self._extract_text_block(self._load_skill_prompt("icebreaker-opening-prompt.md"))
            prompt = (
                prompt.replace("{{历史对话}}", self._format_history(recent_messages))
                .replace("{{当前阶段描述}}", stage_description)
            )
            try:
                with perf_span("llm.interview.icebreaker", model=interview_llm.model):
                    raw = await asyncio.to_thread(
                        interview_llm.chat,
                        "你是一位温和的纪实采访者。只输出一句以“采：”开头的开场破冰话术。",
                        prompt,
                        temperature=0.7,
                        max_tokens=256,
                    )
                return InterviewOpeningResult(reply=self._normalize_reply(raw), response_source="llm")
            except Exception as exc:
                logger.warning("LLM 采访破冰开场失败 model=%s error=%s", interview_llm.model, exc)
                return InterviewOpeningResult(reply=ICEBREAKER_FALLBACK, response_source="fallback")

    async def generate_turn(
        self,
        *,
        user_message: str,
        recent_messages: list[dict[str, str]],
        stage_description: str,
        remaining_rounds: int,
    ) -> InterviewTurnResult:
        with perf_span("interview.turn.total", chars=len(user_message), history=len(recent_messages)):
            if not settings.dashscope_api_key:
                route = self._fallback_route(user_message, remaining_rounds)
                route = self._apply_stage_route_rules(route, stage_description)
                return InterviewTurnResult(
                    reply=self._fallback_reply(route, stage_description, user_message),
                    route=route,
                    response_source="fallback",
                )

            route = await self._judge_route(user_message, recent_messages, remaining_rounds)
            route = self._apply_stage_route_rules(route, stage_description)
            reply = await self._generate_reply(
                route=route,
                user_message=user_message,
                recent_messages=recent_messages,
                stage_description=stage_description,
                remaining_rounds=remaining_rounds,
            )
            return InterviewTurnResult(reply=reply, route=route, response_source="llm")

    async def _judge_route(
        self,
        user_message: str,
        recent_messages: list[dict[str, str]],
        remaining_rounds: int,
    ) -> InterviewRouteResult:
        prompt = self._extract_text_block(self._load_skill_prompt("routing-judgement-prompt.md"))
        prompt = (
            prompt.replace("{{历史对话}}", self._format_history(recent_messages))
            .replace("{{当前阶段建议剩余轮数}}", str(max(0, remaining_rounds)))
            .replace("{{用户本轮回复}}", user_message)
        )
        try:
            with perf_span("llm.interview.route", model=interview_llm.model, chars=len(user_message)):
                raw = await asyncio.to_thread(
                    interview_llm.chat,
                    "你只输出严格 JSON，不输出 Markdown。",
                    prompt,
                    temperature=0.2,
                    max_tokens=512,
                )
            return self._parse_route(raw, user_message, remaining_rounds)
        except Exception as exc:
            logger.warning("LLM 采访路由失败 model=%s error=%s", interview_llm.model, exc)
            return self._fallback_route(user_message, remaining_rounds)

    async def _generate_reply(
        self,
        *,
        route: InterviewRouteResult,
        user_message: str,
        recent_messages: list[dict[str, str]],
        stage_description: str,
        remaining_rounds: int,
    ) -> str:
        prompt = self._build_reply_prompt(route, user_message, recent_messages, stage_description, remaining_rounds)
        try:
            with perf_span(
                "llm.interview.reply",
                model=interview_llm.model,
                route=route.route,
                chars=len(user_message),
            ):
                raw = await asyncio.to_thread(
                    interview_llm.chat,
                    "你是一位温和的纪实采访者。只输出一句以“采：”开头的采访话术。",
                    prompt,
                    temperature=0.7,
                    max_tokens=512,
                )
            return self._normalize_reply(raw)
        except Exception as exc:
            logger.warning("LLM 采访回复失败 model=%s route=%s error=%s", interview_llm.model, route.route, exc)
            return self._fallback_reply(route, stage_description, user_message)

    def _build_reply_prompt(
        self,
        route: InterviewRouteResult,
        user_message: str,
        recent_messages: list[dict[str, str]],
        stage_description: str,
        remaining_rounds: int,
    ) -> str:
        if route.route == "normal_interview":
            prompt = self._build_normal_interview_prompt(remaining_rounds)
            return (
                prompt.replace("{{历史对话}}", self._format_history(recent_messages))
                .replace("{{当前阶段描述}}", stage_description)
                .replace("{{当前阶段建议剩余轮数}}", str(max(0, remaining_rounds)))
                .replace("{{用户本轮输入}}", user_message)
            )

        prompt = self._extract_text_block(self._load_skill_prompt("emotional-support-prompt.md"))
        return (
            prompt.replace("{{历史对话}}", self._format_history(recent_messages))
            .replace("{{当前阶段描述}}", stage_description)
            .replace("{{用户本轮回复}}", user_message)
            .replace("{{路由判断结果}}", route.model_dump_json(ensure_ascii=False))
        )

    def _build_normal_interview_prompt(self, remaining_rounds: int) -> str:
        doc = self._load_skill_prompt("normal-interview-prompt.md")
        base = self._section_code_block(doc, "## 基础提示词")
        normal = self._section_code_block(doc, "## 普通轮次节奏提示词")
        low_round = self._section_code_block(doc, "## 低轮数兴趣判断提示词")
        input_block = self._section_code_block(doc, "## 输入区")
        rhythm = normal if remaining_rounds > 3 else low_round
        return "\n\n".join([base, rhythm, input_block])

    @staticmethod
    def _parse_route(raw: str, user_message: str, remaining_rounds: int) -> InterviewRouteResult:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
            text = re.sub(r"```$", "", text).strip()
        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.S)
            data = json.loads(match.group(0)) if match else {}
        try:
            route = InterviewRouteResult.model_validate(data)
        except Exception:
            route = InterviewAgentService._fallback_route(user_message, remaining_rounds)
        if route.route in {"resistance_turn", "strong_emotional_guidance", "implicit_low_engagement"}:
            route.round_decrement = 1
        route.round_decrement = 0 if route.round_decrement == 0 else 1
        return route

    @staticmethod
    def _fallback_route(user_message: str, remaining_rounds: int) -> InterviewRouteResult:
        text = user_message.strip()
        resistance_words = ["不想说", "别提", "算了", "没必要", "过去了", "不愿提", "不多说", "跳过"]
        low_words = ["嗯", "还行", "就这样", "差不多", "没什么", "记不清", "想不起来"]
        high_markers = ["我还记得", "有一次", "那时候", "后来", "现在想起来", "印象很深", "难忘"]
        if any(word in text for word in resistance_words):
            return InterviewRouteResult(
                route="resistance_turn",
                emotion_type="mixed",
                confidence=0.7,
                reason="用户文字中出现明确回避或终止当前话题的表达。",
                should_change_topic=True,
                do_not_probe_current_topic=True,
                round_decrement=1,
            )
        if len(text) <= 8 or any(word in text for word in low_words):
            return InterviewRouteResult(
                route="implicit_low_engagement",
                emotion_type="unclear",
                confidence=0.6,
                reason="用户回复较短或表示记不清，适合降低压力。",
                should_change_topic=True,
                do_not_probe_current_topic=False,
                round_decrement=1,
            )
        round_decrement = 0 if remaining_rounds <= 3 and len(text) >= 40 and any(m in text for m in high_markers) else 1
        return InterviewRouteResult(
            route="normal_interview",
            emotion_type="none",
            confidence=0.5,
            reason="用户回复包含可继续追问的信息。",
            should_change_topic=False,
            do_not_probe_current_topic=False,
            round_decrement=round_decrement,
        )

    @staticmethod
    def _fallback_reply(route: InterviewRouteResult, stage_description: str = "", user_message: str = "") -> str:
        if route.route == "resistance_turn":
            return "采：好的，我尊重您的想法，这段我们就不聊了。接下来换个轻松些的话题，说说现在生活里让您觉得舒心的小事吧？"
        if route.route == "implicit_low_engagement":
            return "采：没关系，想不起来的地方咱们就不勉强了。换个轻松点的角度说说，现在什么事最让您觉得踏实？"
        if route.route == "strong_emotional_guidance":
            return "采：能感受到这段经历让您有些沉重，咱们先把这部分放一放，说说后来让您觉得温暖的人和事吧？"
        if "S0" in stage_description:
            return "采：那种简单又亲近的日子，往往最容易留在心里。那我们就先从小时候聊起，您小时候是在什么样的地方长大的？"
        if "本轮采访任务：日常主线与关键事件" in stage_description:
            return "采：这样的大环境就有了轮廓。那平日里您主要都在忙些什么？这段日子里，有没有哪件事让您到现在还印象很深？"
        if "本轮采访任务：人际联结" in stage_description:
            return "采：一段日子里，身边的人往往最能让记忆有温度。那时候陪在您身边、或者和您一起撑着往前走的，主要是哪些人呢？"
        if "本轮采访任务：心境得失" in stage_description:
            return "采：回头看这段时光，它给您留下最大的收获、改变，或者最深的感触是什么？"
        if "本轮采访任务：阶段收束与下一阶段开启" in stage_description:
            return "采：这段经历先聊到这里，已经能看见当时的大致样子了。往后走到下一段日子时，您当时的生活环境和处境又变成了什么样？"
        return INTERVIEW_FALLBACK

    @staticmethod
    def _apply_stage_route_rules(route: InterviewRouteResult, stage_description: str) -> InterviewRouteResult:
        if "S0" in stage_description and route.route == "normal_interview":
            route.round_decrement = 1
            route.emotion_type = "none"
        return route

    @staticmethod
    def _format_history(messages: list[dict[str, str]]) -> str:
        if not messages:
            return "暂无历史对话。"
        lines: list[str] = []
        for msg in messages[-16:]:
            role = "采" if msg.get("role") == "assistant" else "受"
            content = str(msg.get("content") or "").strip()
            if content:
                lines.append(f"{role}：{content}")
        return "\n".join(lines) if lines else "暂无历史对话。"

    @staticmethod
    def _normalize_reply(raw: str) -> str:
        text = raw.strip().strip('"')
        if not text.startswith("采："):
            text = f"采：{text}"
        return text

    @staticmethod
    def _load_skill_prompt(name: str) -> str:
        path = SKILL_REFERENCES_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"Skill prompt not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _extract_text_block(markdown: str) -> str:
        match = re.search(r"```text\s*(.*?)```", markdown, re.S)
        return match.group(1).strip() if match else markdown.strip()

    @staticmethod
    def _section_code_block(markdown: str, section_title: str) -> str:
        start = markdown.find(section_title)
        if start < 0:
            raise ValueError(f"Section not found: {section_title}")
        tail = markdown[start:]
        match = re.search(r"```text\s*(.*?)```", tail, re.S)
        if not match:
            raise ValueError(f"Text block not found in section: {section_title}")
        return match.group(1).strip()
