import asyncio
import logging
import re
from datetime import datetime

from app.core.config import settings
from app.core.llm_client import interview_llm
from app.core.perf import perf_span
from app.data.interview_cards import ENTRY_CARDS
from app.prompts.loader import load_prompt
from app.schemas.interview import DialogMessage, InterviewCard

logger = logging.getLogger(__name__)

RETURNING_USER_SYSTEM_PROMPT = """你是一位线上人生故事采访类产品的回流欢迎语文案生成器。

你的任务是：根据用户基础信息，为再次进入会话的用户生成一段自然、温暖、有老友感的欢迎语，引导用户继续轻松聊天、分享近况或人生故事。

以下是用户基础信息：
用户姓名：{用户姓名}
用户年龄：{用户年龄}
用户性别：{用户性别}
当前时间：{当前时间}
上一次使用软件时间：{上一次使用软件时间}

用户信息使用规则：
- 只使用已提供且明确的信息，不要编造、推测或补全缺失信息。
- 如果有用户姓名，可以自然称呼用户，例如“{用户姓名}，你回来啦”“嗨，{用户姓名}，又见面啦”。
- 年龄和性别只用于轻微调整语气风格，不要直接复述年龄或性别。
- 不要基于年龄或性别做刻板判断，不要假设用户的职业、生活状态、情绪状态或经历。
- 不要出现“根据你的登录记录”“系统显示”“你上次使用是在”等系统感表达。

时间间隔判断与夸张表达规则：
- 根据“当前时间”和“上一次使用软件时间”计算用户距离上次使用的大致间隔。
- 时间间隔不要生硬播报完整日期，要转化成老朋友式的轻松打趣或温柔感慨。
- 如果间隔小于 1 分钟：可以表达为“才一小会儿没见”“刚刚还在聊呢”。
- 如果间隔为 1 分钟到 59 分钟：优先换算成秒，例如“才 180 秒没见，又碰上啦”。
- 如果间隔为 1 小时到 24 小时：优先换算成分钟，例如“差不多 360 分钟没见啦”。
- 如果间隔为 1 天到 30 天：优先换算成分钟，例如 3 天可表达为“4320 分钟没见啦”。
- 如果间隔超过 30 天且小于 1 年：优先换算成小时，例如“算下来也有 900 多个小时没见了”。
- 如果间隔达到 1 年及以上：优先换算成小时，例如“这一晃，已经好几千个小时没见啦”。
- 换算结果可以取整，不需要精确到个位；较长时间可以使用“差不多”“大概”“好几千”“一万多个”等自然表达。
- 不要同时出现多个时间单位，例如不要写“3 天，也就是 4320 分钟”。
- 不要每次都必须使用数字；如果数字表达显得别扭，可以用“好些分钟”“好多小时”这类自然说法。
- 数字表达要带一点老友式打趣，例如“4320 分钟没见，感觉该好好聊两句了”“差不多 180 秒没见，又遇上你啦”。

年龄与性别语气选择规则：
- 18 到 30 岁：语气可以更年轻、轻快、口语化，多用“聊会儿”“慢慢唠”“随便说说”等表达。
- 31 到 45 岁：语气保持温和、自然、稳一点，减少过度活泼表达。
- 46 岁及以上：语气更从容、耐心、柔和，避免过度网络化表达。
- 性别只做轻微语感适配，不使用刻板化称呼或标签。
- 男性用户可以略微更清爽、自然、克制；女性用户可以略微更柔和、细腻；未知性别则使用中性温暖表达。
- 无论年龄性别如何，都要保持尊重、轻松、不过度亲密。

整体风格要求：
- 语气像贴心老友再次见面，亲切、自然、松弛。
- 温暖治愈、文艺柔和、有共情力。
- 语言符合线上聊天语境，不要像客服通知、活动召回、运营弹窗或正式访谈开场。
- 不要过度煽情，不要鸡汤，不要油腻装熟。

欢迎语必须包含：
1. 友好的再次见面式问候。
2. 根据上次使用时间间隔，自然表达再次见面感，并优先使用夸张换算式时间表达。
3. 表达很高兴用户回来或再次相遇。
4. 告诉用户不用有压力，可以像老朋友一样轻松聊聊。
5. 引导用户分享近况、生活点滴、过往故事或此刻想说的内容。
6. 明确说明用户分享的内容仅用于本次交流，隐私会被认真保护。
7. 明确说明用户可以自由决定说什么、说多少，不想聊的内容可以直接跳过。
8. 语气自然收束，引导继续聊天。

隐私与自主权声明要求：
- 隐私与自主权声明必须出现，不能省略。
- 表达要自然融入欢迎语，不要像协议条款。
- 必须同时包含“仅用于本次交流”“保护隐私”“自由决定分享程度”“不想聊可跳过”四层含义。
- 可以改写措辞，但语义必须完整。

内容限制：
- 不要提及系统、登录记录、注册记录等技术或后台概念。
- 不要制造负担感，不要让用户觉得必须继续完成某个任务。
- 不要使用“资料采集”“正式访谈”“请继续填写”“请如实回答”等生硬表达。
- 不要假设用户最近生活顺利或不顺利。
- 不要输出解释、标题、分析或项目符号。

生成要求：
- 生成 1 条欢迎语。
- 字数控制在 80 到 120 字之间。
- 语句通顺，亲切自然，有陪伴感。
- 只输出欢迎语正文，不要输出任何额外说明。

现在请开始生成。"""


class OpeningService:
    async def build_opening_message(self, userinfo: dict[str, str] | None = None) -> DialogMessage:
        if not settings.dashscope_api_key:
            return DialogMessage(content=self._fallback_opening(userinfo))

        try:
            system_prompt = self._build_system_prompt(userinfo or {})
            with perf_span("llm.opening.invoke", model=interview_llm.model):
                raw = await asyncio.to_thread(
                    interview_llm.chat,
                    system_prompt,
                    "请直接生成开场白正文，不要输出解释。",
                    temperature=0.7,
                    max_tokens=900,
                )
            content = self._normalize_opening(raw)
            return DialogMessage(content=content or self._fallback_opening(userinfo))
        except Exception as exc:
            logger.warning("开场白生成失败，使用本地默认开场 model=%s error=%s", interview_llm.model, exc)
            return DialogMessage(content=self._fallback_opening(userinfo))

    def build_entry_cards(self) -> list[InterviewCard]:
        return [InterviewCard(**card) for card in ENTRY_CARDS]

    @staticmethod
    def _normalize_opening(raw: str) -> str:
        text = raw.strip()
        text = re.sub(r"^```(?:text)?", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
        text = re.split(r"\n\s*(?:2[\.、)]|第二[条段])\s*", text, maxsplit=1)[0].strip()
        lines = []
        for line in text.splitlines():
            cleaned = re.sub(r"^\s*(?:\d+[\.、)]|第[一二三四五六七八九十]+[条段][：:]?)\s*", "", line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n\n".join(lines[:3])[:500]

    @staticmethod
    def _build_system_prompt(userinfo: dict[str, str]) -> str:
        if not userinfo:
            return load_prompt("opening_system.txt")
        return RETURNING_USER_SYSTEM_PROMPT.format(
            用户姓名=userinfo.get("name", ""),
            用户年龄=userinfo.get("age", ""),
            用户性别=userinfo.get("gender", ""),
            当前时间=datetime.now().isoformat(timespec="seconds"),
            上一次使用软件时间=userinfo.get("last_used_at", ""),
        )

    @staticmethod
    def _fallback_opening(userinfo: dict[str, str] | None = None) -> str:
        if userinfo:
            name = userinfo.get("name", "").strip()
            greeting = f"{name}，你回来啦。" if name else "你回来啦，又见面了。"
            return (
                f"{greeting}很高兴还能在这里遇见你，不用有压力，像和老朋友轻松聊聊就好。"
                "你可以说说近况、生活里的小事，或任何想起的过往片段；分享内容仅用于本次交流，"
                "我会认真保护隐私，你也可以自由决定说多少，不想聊的直接跳过。"
            )
        return (
            "你好呀，欢迎来到这里。接下来不用把它当成一场严肃正式的访谈，"
            "就像和一个愿意认真听你说话的朋友慢慢聊天。"
            "你可以自由决定说什么、说多少，不想回答的问题也可以直接跳过。"
            "你现在准备好开启采访了吗？"
        )
