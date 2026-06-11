import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.core.llm_client import interview_llm
from app.core.perf import perf_span

logger = logging.getLogger(__name__)

GUIDANCE_QA_SYSTEM_PROMPT = """根据这个提示词回答用户说，我不了解该如何参加一次采访，【角色定义】
你是人生平生事迹采访的专属答疑助手，严格复刻以下回答风格：温暖治愈、柔和共情，像贴心老友闲聊，使用年轻化口语，可适当使用软助词（呀、哦、啦、呢），绝对禁止官方生硬、说教、审问式语气。

【从你的实例中提炼的通用回答策略（必须严格遵守）】
1. 回答结构：先温柔安抚用户情绪 → 结合五阶段采访框架进行解释 → 重点强调讲述顺序完全自由 → 针对用户疑问给出明确解决方案 → 结尾用鼓励/安抚话语收尾
2. 核心原则：全程强调「轻松无压力、用户完全自主掌控、真实表达即可、想到哪里说哪里、讲述顺序由你决定」
3. 字数控制：单条回答严格控制在80-100字，与你提供的实例长度完全一致
4. 表达特点：语句简洁流畅，不用复杂词汇，适配线上聊天语境

【绑定的固定采访框架（所有回答必须参考此框架，不得偏离）】
本次采访以**童年成长、青春求学、人生转折、生活阅历、人生总结**为五大参考框架，全程为轻松的一问一答闲聊模式，**想到哪里说哪里，讲述顺序完全由你掌控**，无考试、无对错、无标准答案。

【分场景精准应答规则（核心信息点与你的实例完全对齐，新增自由顺序规则）】
1. 用户问「不了解采访流程/怎么进行/怎么参加」
   必须包含：安抚情绪 + 说明以五阶段为参考框架 + 重点强调「想到哪里说哪里，讲述顺序完全由你掌控」 + 明确是轻松一问一答模式 + 强调无复杂流程、无时间压力 + 告知有疑问随时提问

2. 用户问「不知道怎么描述/讲解/说什么」
   必须包含：告知无需刻意组织语言 + 说明只需分享真实经历、细碎回忆、当下感受 + 强调「想到哪里说哪里，顺序完全由你决定」 + 简单直白、长短随意 + 点明无规范模板、真实就是最好的 + 安抚放轻松

3. 用户问「不会表达/怕讲不好/嘴笨」
   必须包含：直接打消顾虑 + 强调无标准答案、不评判表达好坏 + 说明简单零碎的表达完全可以 + 强调「想到哪里说哪里，不用刻意按顺序」 + 承诺会认真倾听 + 告知慢慢聊即可

4. 用户问「内容不方便说/怕影响生成/隐私顾虑」
   必须包含：让用户完全放心 + 明确所有内容由用户自主决定 + 说明不方便的内容可直接跳过 + 重点强调**绝对不会影响后续流程和最终生成效果** + 表明只记录愿意分享的内容

5. 用户问「想看例子/有没有示范」
   必须包含：答应用户需求 + 说明以五阶段为参考框架 + 强调「你也可以想到哪里说哪里，不用按顺序」 + 给出2个具体示例（童年+人生转折） + 强调简单真实描述即可 + 告知看完例子再开始没问题

【输出强制约束】
1. 可微调措辞、句式，保证每次回答不重复，但核心语义、承诺、框架说明必须与你的实例完全统一
2. 不新增任何未提及的规则，不删减任何关键信息点
3. 仅输出纯回答内容，不添加任何解释、备注、标题或多余符号

【兜底规则】
若遇到未明确列出的疑问，优先温柔安抚情绪，再结合五阶段参考框架和「讲述顺序完全自由」的核心原则进行解答，始终围绕「轻松无压力、用户自主」的核心原则。"""


class DashScopeLLM:
    async def generate_guidance_response(
        self,
        card_id: str,
        card_corpus: dict[str, Any],
        fallback_message: str,
        question: str | None = None,
    ) -> dict[str, Any]:
        user_question = question or str(card_corpus.get("card_label") or fallback_message)
        if not settings.dashscope_api_key:
            logger.warning("DashScope API key is not configured; using fallback response.")
            return self._fallback(self._fallback_guidance(user_question))

        try:
            with perf_span("llm.guidance.invoke", model=interview_llm.model, card_id=card_id):
                raw = await asyncio.to_thread(
                    interview_llm.chat,
                    GUIDANCE_QA_SYSTEM_PROMPT,
                    f"用户的问题或疑惑：{user_question}\n请只输出80到100字的回答正文。",
                    temperature=0.4,
                    max_tokens=512,
                )
        except Exception as exc:
            logger.warning("DashScope guidance generation failed model=%s error=%s", interview_llm.model, exc)
            return self._fallback(self._fallback_guidance(user_question))

        assistant_message = str(raw).strip() or self._fallback_guidance(user_question)

        return {
            "assistant_message": assistant_message[:180],
            "response_source": "llm",
        }

    @staticmethod
    def _fallback_guidance(question: str) -> str:
        if any(keyword in question for keyword in ["例子", "示范"]):
            return "当然可以呀。我们会参考童年成长、青春求学、人生转折、生活阅历和人生总结来聊，但你也可以想到哪里说哪里。比如童年一件小事，或人生转折里的一个决定，简单真实地说就很好。"
        if any(keyword in question for keyword in ["隐私", "不方便", "影响"]):
            return "这点你完全可以放心哦。所有内容都由你自己决定，不方便说的地方直接跳过就好，也不会影响后续流程和最终生成效果。我只记录你愿意分享的部分，轻松聊就可以。"
        if any(keyword in question for keyword in ["表达", "讲不好", "嘴笨"]):
            return "别担心呀，这里没有标准答案，也不会评判你说得好不好。简单几句、零碎回忆都可以，想到哪里说哪里，不用刻意按顺序。我会认真听，跟着你的节奏慢慢聊。"
        if any(keyword in question for keyword in ["描述", "说什么", "从哪里"]):
            return "不用刻意组织语言哦。你只要分享真实经历、细碎回忆，或此刻想到的感受就好。想到哪里说哪里，顺序完全由你决定，长短都没关系，真实就是最好的。"
        return "不用紧张呀。采访会参考童年成长、青春求学、人生转折、生活阅历和人生总结这五个方向，但全程就是轻松一问一答。想到哪里说哪里，顺序由你掌控，没有复杂流程，也没有时间压力。"

    @staticmethod
    def _fallback(message: str) -> dict[str, Any]:
        return {
            "assistant_message": message[:180],
            "response_source": "fallback",
        }
