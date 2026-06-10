"""
心理状态卡片语料库配置
后续可替换为数据库或运营后台配置
"""

from typing import Optional

CARD_CORPUS = {
    "relaxed_slow": {
        "card_id": "relaxed_slow",
        "label": "放松自在，想慢慢回忆故事",
        "user_psychology": "接受度高，节奏偏慢",
        "response_strategy": "slow_start",
        "assistant_message": "那我们就慢慢来，不急着讲完整。您想到哪里，我就帮您记到哪里。",
        "next_question": "您要不要先从印象最深的一个地方开始说起？",
    },
    "emotional_memory": {
        "card_id": "emotional_memory",
        "label": "有点感慨，愿意聊聊过往",
        "user_psychology": "情绪被触动，可能需要温柔承接",
        "response_strategy": "comfort",
        "assistant_message": "有些回忆一想起来确实会有很多感受。您可以只讲愿意讲的部分，我会帮您好好记录。",
        "next_question": "您现在最想说的是哪一段时光？",
    },
    "unknown_process": {
        "card_id": "unknown_process",
        "label": "采访是以什么方式进行的，我不了解",
        "user_psychology": "对流程不确定",
        "response_strategy": "explain_process",
        "assistant_message": "方式很简单，我会像聊天一样问几个小问题，您不用准备，也不用一次讲完整。",
        "next_question": "我们可以先从一些简单的事情聊起，比如您小时候住在哪里？",
    },
    "restrained": {
        "card_id": "restrained",
        "label": "略带拘谨，不太习惯表达",
        "user_psychology": "表达压力、自我效能低",
        "response_strategy": "comfort",
        "assistant_message": "没关系，讲得零散也可以。您说几个词、几句话，我也能帮您慢慢整理成故事。",
        "next_question": "您能想到的，哪怕只是一个地名、一个人名都可以。",
    },
    "enthusiastic": {
        "card_id": "enthusiastic",
        "label": "兴致满满，很乐意分享",
        "user_psychology": "高参与度",
        "response_strategy": "quick_start",
        "assistant_message": "太好了，那我们可以直接开始。先从您最想被家人记住的一段经历说起，或者从小时候说起都可以。",
        "next_question": "您最想让家人知道的是哪段经历？",
    },
    "scattered": {
        "card_id": "scattered",
        "label": "思绪杂乱，不知从何说起",
        "user_psychology": "需要结构引导",
        "response_strategy": "provide_structure",
        "assistant_message": "我们可以不用按顺序来。您可以从一个人、一个地方，或一件现在还记得的小事开始。",
        "next_question": "您现在脑子里最先浮现的是一个人、一个地方，还是一件事？",
    },
}

MAIN_CARDS = [
    {
        "card_id": "start_interview",
        "label": "直接开始采访",
        "next_action": "ENTER_INTERVIEW",
    },
    {
        "card_id": "need_guidance",
        "label": "我还没想好怎么说",
        "next_action": "SHOW_GUIDANCE_CARD",
    },
]

PSYCHOLOGY_CARDS = [
    {"card_id": card_id, "label": card["label"]}
    for card_id, card in CARD_CORPUS.items()
]


def get_card_by_id(card_id: str) -> Optional[dict]:
    return CARD_CORPUS.get(card_id)


def get_main_cards() -> list[dict]:
    return MAIN_CARDS


def get_psychology_cards() -> list[dict]:
    return PSYCHOLOGY_CARDS