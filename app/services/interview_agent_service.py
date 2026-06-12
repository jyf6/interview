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

MAX_HISTORY_MESSAGES = 8
MAX_HISTORY_MESSAGE_CHARS = 500
HIGH_ENGAGEMENT_MIN_CHARS = 40

RESISTANCE_WORDS = ["不想说", "别提", "算了", "没必要", "过去了", "不愿提", "不多说", "跳过"]
LOW_ENGAGEMENT_WORDS = ["嗯", "还行", "就这样", "差不多", "没什么", "记不清", "想不起来"]
MILD_EMOTION_WORDS = ["有点遗憾", "挺感慨", "不容易", "不是滋味", "有些后悔", "有点想念", "怀念"]
STRONG_EMOTION_WORDS = ["越想越难受", "都怪我", "特别后悔", "憋得慌", "压力太大", "放不下", "开心不起来", "没人说话"]
HIGH_ENGAGEMENT_MARKERS = [
    "我还记得",
    "特别记得",
    "有一次",
    "那时候",
    "那会儿",
    "当时",
    "后来",
    "结果",
    "因为",
    "所以",
    "现在想起来",
    "到现在",
    "印象很深",
    "印象最深",
    "难忘",
    "最难忘",
    "第一次",
    "我们那片",
    "我们那个院子",
    "我们那条巷子",
    "我们那个年级",
    "我们那个车间",
    "我们那个圈子",
    "大家都",
    "周围的人",
    "那几年",
    "一直没变",
    "后来影响",
]
RELATION_SUPPORT_MARKERS = [
    "女朋友",
    "男朋友",
    "对象",
    "恋人",
    "爱人",
    "伴侣",
    "妻子",
    "丈夫",
    "老婆",
    "老公",
    "朋友",
    "同事",
    "师傅",
    "老师",
    "家人",
]
SUPPORT_ACTION_MARKERS = ["鼓励", "支持", "陪", "帮", "帮助", "撑着", "安慰", "照顾", "陪伴"]

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
    "extended_interview",
    "emotional_guidance",
]


class InterviewRouteResult(BaseModel):
    route: RouteName = "normal_interview"
    emotion_type: str = "none"
    confidence: float = 0.0
    reason: str = ""
    should_change_topic: bool = False
    do_not_probe_current_topic: bool = False
    round_decrement: int = Field(default=1, ge=0, le=1)
    detected_stage: str = "unclear"
    stage_shift_reason: str = ""
    skip_completed_stages: bool = False


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
        if route.route in {"normal_interview", "extended_interview"}:
            prompt = self._build_normal_interview_prompt(route, remaining_rounds)
            return (
                prompt.replace("{{历史对话}}", self._format_history(recent_messages))
                .replace("{{当前阶段描述}}", stage_description)
                .replace("{{当前阶段建议剩余轮数}}", str(max(0, remaining_rounds)))
                .replace("{{用户本轮输入}}", user_message)
                .replace("{{路由判断结果}}", route.model_dump_json(ensure_ascii=False))
            )

        prompt = self._extract_text_block(self._load_skill_prompt("emotional-support-prompt.md"))
        return (
            prompt.replace("{{历史对话}}", self._format_history(recent_messages))
            .replace("{{当前阶段描述}}", stage_description)
            .replace("{{用户本轮回复}}", user_message)
            .replace("{{路由判断结果}}", route.model_dump_json(ensure_ascii=False))
        )

    def _build_normal_interview_prompt(self, route: InterviewRouteResult, remaining_rounds: int) -> str:
        if route.route == "extended_interview":
            return self._extract_text_block(self._load_skill_prompt("detail-followup-prompt.md"))

        doc = self._load_skill_prompt("normal-interview-prompt.md")
        base = self._section_code_block(doc, "## 基础提示词")
        normal = self._section_code_block(doc, "## 普通轮次节奏提示词")
        low_round = self._section_code_block(doc, "## 阶段收束提示词")
        input_block = self._section_code_block(doc, "## 输入区")
        rhythm = normal if remaining_rounds > 1 else low_round
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
        if route.detected_stage not in {"S1", "S2", "S3", "S4", "S5", "unclear"}:
            route.detected_stage = "unclear"
        local_stage = InterviewAgentService._detect_stage(user_message)
        if local_stage != "unclear" and route.detected_stage != local_stage:
            route.detected_stage = local_stage
        if route.route == "extended_interview":
            route.round_decrement = 0
        elif route.route == "normal_interview":
            route.round_decrement = 1
        elif route.route == "emotional_guidance":
            low_or_resistant = InterviewAgentService._is_low_engagement_or_resistant(user_message)
            emotional_content = InterviewAgentService._has_emotional_content(user_message)
            route.round_decrement = 1 if low_or_resistant or emotional_content or route.round_decrement == 1 else 0
        route.round_decrement = 0 if route.round_decrement == 0 else 1
        return route

    @staticmethod
    def _fallback_route(user_message: str, remaining_rounds: int) -> InterviewRouteResult:
        text = user_message.strip()
        if any(word in text for word in RESISTANCE_WORDS):
            return InterviewRouteResult(
                route="emotional_guidance",
                emotion_type="mixed",
                confidence=0.7,
                reason="用户文字中出现明确回避或终止当前话题的表达。",
                should_change_topic=True,
                do_not_probe_current_topic=True,
                round_decrement=1,
                stage_shift_reason="用户抵触当前扩展话题，建议停止该支线并回到当前阶段尚未完成的主问题。",
                skip_completed_stages=False,
            )
        if len(text) <= 8 or any(word in text for word in LOW_ENGAGEMENT_WORDS):
            return InterviewRouteResult(
                route="emotional_guidance",
                emotion_type="unclear",
                confidence=0.6,
                reason="用户回复较短或表示记不清，适合降低压力。",
                should_change_topic=True,
                do_not_probe_current_topic=False,
                round_decrement=1,
                stage_shift_reason="用户回复较短或记不清，建议降低压力并回到当前阶段尚未完成的主问题。",
                skip_completed_stages=False,
            )
        if any(word in text for word in STRONG_EMOTION_WORDS):
            return InterviewRouteResult(
                route="emotional_guidance",
                emotion_type="mixed",
                confidence=0.7,
                reason="用户文字中出现明显负面情绪负担，适合先安抚再回到轻松方向。",
                should_change_topic=True,
                do_not_probe_current_topic=True,
                round_decrement=1,
            )
        if any(word in text for word in MILD_EMOTION_WORDS):
            return InterviewRouteResult(
                route="emotional_guidance",
                emotion_type="sadness",
                confidence=0.65,
                reason="用户文字中出现轻度感慨或怀念，适合轻轻共情后继续低压力追问。",
                should_change_topic=False,
                do_not_probe_current_topic=False,
                round_decrement=1,
            )
        if InterviewAgentService._is_high_engagement_followup_candidate(text):
            return InterviewRouteResult(
                route="extended_interview",
                emotion_type="none",
                confidence=0.55,
                reason="用户回复包含可扩展传记素材，适合单步试探追问。",
                should_change_topic=False,
                do_not_probe_current_topic=False,
                round_decrement=0,
                detected_stage=InterviewAgentService._detect_stage(text),
            )
        return InterviewRouteResult(
            route="normal_interview",
            emotion_type="none",
            confidence=0.5,
            reason="用户回复可继续按主流程推进。",
            should_change_topic=False,
            do_not_probe_current_topic=False,
            round_decrement=1,
            detected_stage=InterviewAgentService._detect_stage(text),
        )

    @staticmethod
    def _is_high_engagement_followup_candidate(user_message: str) -> bool:
        text = user_message.strip()
        if any(word in text for word in RESISTANCE_WORDS):
            return False
        if any(word in text for word in LOW_ENGAGEMENT_WORDS):
            return False
        if InterviewAgentService._has_relationship_support_material(text):
            return True
        marker_count = sum(1 for marker in HIGH_ENGAGEMENT_MARKERS if marker in text)
        if marker_count >= 1:
            return True
        if len(text) < HIGH_ENGAGEMENT_MIN_CHARS:
            return False
        sentence_breaks = sum(text.count(mark) for mark in ("，", "。", "；", ",", ".", ";"))
        return len(text) >= 80 and sentence_breaks >= 2

    @staticmethod
    def _has_relationship_support_material(user_message: str) -> bool:
        text = user_message.strip()
        return any(person in text for person in RELATION_SUPPORT_MARKERS) and any(
            action in text for action in SUPPORT_ACTION_MARKERS
        )

    @staticmethod
    def _is_low_engagement_or_resistant(user_message: str) -> bool:
        text = user_message.strip()
        return len(text) <= 8 or any(word in text for word in RESISTANCE_WORDS + LOW_ENGAGEMENT_WORDS)

    @staticmethod
    def _is_resistant(user_message: str) -> bool:
        text = user_message.strip()
        return any(word in text for word in RESISTANCE_WORDS)

    @staticmethod
    def _has_emotional_content(user_message: str) -> bool:
        text = user_message.strip()
        return any(word in text for word in MILD_EMOTION_WORDS + STRONG_EMOTION_WORDS)

    @staticmethod
    def _detect_stage(user_message: str) -> str:
        text = user_message.strip()
        if not text:
            return "unclear"

        def has_any(words: list[str]) -> bool:
            return any(word in text for word in words)

        age_matches = [int(match) for match in re.findall(r"(?<!\d)(\d{1,2})\s*岁", text)]
        mentions_child_age = any(age <= 12 for age in age_matches) or has_any(
            ["十二岁以前", "12岁以前", "上小学", "小学时候", "小学那会", "小学那阵", "小学", "小时候", "童年", "儿时", "孩提"]
        )
        mentions_work = has_any(
            ["打工", "上班", "工作", "做工", "进厂", "工厂", "车间", "外出务工", "外地务工", "外出打工", "外地打工", "深圳", "广东", "南下"]
        )
        mentions_family_responsibility = has_any(
            ["结婚", "成家", "婚后", "生子", "孩子出生", "养孩子", "养家", "供孩子", "家庭责任", "责任", "一家人", "搬家", "买房"]
        )

        if has_any(["这一生", "一辈子", "人生道理", "留给", "最后的话", "回头看这一生", "总结一下", "遗憾", "感谢"]):
            return "S5"
        if has_any(["退休", "晚年", "孙子", "孙女", "外孙", "外孙女", "老了以后", "现在生活", "如今生活", "身体"]):
            return "S4"
        if mentions_family_responsibility:
            return "S3"
        if mentions_work:
            return "S2"
        if has_any(["上学", "读书", "离家", "年轻", "年轻时", "青春", "学徒", "参军", "初入社会", "朋友", "理想"]):
            return "S2"
        if mentions_child_age or (
            has_any(["出生", "父母", "兄弟", "姐妹", "家里条件", "玩伴"])
            and has_any(["小时候", "童年", "儿时", "小学", "那时年纪小", "小时"])
        ):
            return "S1"
        return "unclear"

    @staticmethod
    def _fallback_reply(route: InterviewRouteResult, stage_description: str = "", user_message: str = "") -> str:
        if "本轮采访任务：最终收尾" in stage_description:
            return "采：谢谢您愿意把这些人生经历慢慢讲给我听，这些故事都很珍贵，今天的采访就先到这里。"
        if route.route == "emotional_guidance" and InterviewAgentService._is_resistant(user_message):
            return f"采：好的，您不想再提这段，我尊重您的想法，咱们就不顺着这里深聊了。{InterviewAgentService._fallback_main_question(stage_description)}"
        if route.route == "emotional_guidance" and InterviewAgentService._is_low_engagement_or_resistant(user_message):
            return f"采：没关系，您现在想不起来，咱们就不勉强这段了。{InterviewAgentService._fallback_main_question(stage_description)}"
        if route.route == "emotional_guidance":
            return f"采：能感受到这段经历让您有些沉重，咱们不深挖难受的地方。{InterviewAgentService._fallback_main_question(stage_description)}"
        if route.route == "extended_interview":
            return "采：您刚提到的这个点挺有故事感的。那件事后来对您有什么影响，或者让您一直记到现在的是什么？"
        if "本轮采访任务：日常主线与关键事件" in stage_description:
            return "采：您刚才说的这些，让那段日子的轮廓清楚了一些。那平日里您主要都在忙些什么？"
        if "本轮采访任务：人际联结" in stage_description:
            return "采：您刚才讲到的那段经历里，身边的人应该也很重要。那时候陪在您身边、或者和您一起撑着往前走的，主要是哪些人呢？"
        if "本轮采访任务：心境得失" in stage_description:
            return "采：您刚才说的这些，听起来确实是一段会留下痕迹的日子。回头看，它给您留下最大的收获、改变，或者最深的感触是什么？"
        if "本轮采访任务：阶段收束与下一阶段开启" in stage_description:
            return "采：这段经历先聊到这里，已经能看见当时的大致样子了。往后走到下一段日子时，您的生活环境和处境又变成了什么样？"
        return INTERVIEW_FALLBACK

    @staticmethod
    def _fallback_main_question(stage_description: str) -> str:
        if "本轮采访任务：环境与处境" in stage_description:
            return "换个轻一点的角度说说，那段时期您的生活环境和处境大概是什么样的？"
        if "本轮采访任务：日常主线" in stage_description:
            return "那段时期平日里主要是怎么过的，每天最常忙些什么？"
        if "本轮采访任务：关键事件" in stage_description:
            return "这段时期里，有没有一件比较有代表性的事，让您到现在还记得？"
        if "本轮采访任务：人际与心境" in stage_description:
            return "那时候身边对您比较重要的人是谁，这段经历后来给您留下了什么影响？"
        return "换个轻一点的角度说说，这段日子里还有哪些您愿意提一提的事情？"

    @staticmethod
    def _apply_stage_route_rules(route: InterviewRouteResult, stage_description: str) -> InterviewRouteResult:
        return route

    @staticmethod
    def _format_history(messages: list[dict[str, str]]) -> str:
        if not messages:
            return "暂无历史对话。"
        lines: list[str] = []
        for msg in messages[-MAX_HISTORY_MESSAGES:]:
            role = "采" if msg.get("role") == "assistant" else "受"
            content = str(msg.get("content") or "").strip()[:MAX_HISTORY_MESSAGE_CHARS]
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
