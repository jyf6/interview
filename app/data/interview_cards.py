ENTRY_CARDS = [
    {
        "card_id": "start_interview",
        "label": "直接开始采访",
    },
    {
        "card_id": "need_guidance",
        "label": "我还有点顾虑",
    },
]

GUIDANCE_CARDS = [
    {
        "card_id": "relaxed_slow",
        "label": "我想放松一点，慢慢回忆",
    },
    {
        "card_id": "emotional_memory",
        "label": "有些回忆让我有点感慨",
    },
    {
        "card_id": "unknown_process",
        "label": "我不太了解采访会怎么进行",
    },
    {
        "card_id": "restrained",
        "label": "我不太习惯表达，怕讲不好",
    },
    {
        "card_id": "enthusiastic",
        "label": "我愿意分享，可以直接聊",
    },
    {
        "card_id": "scattered",
        "label": "我思绪有点乱，不知道从哪里说起",
    },
]

CARD_RESPONSE_CORPUS = {
    "relaxed_slow": {
        "card_label": "我想放松一点，慢慢回忆",
        "scene": "用户接受度较高，但希望节奏慢一些。",
        "user_state": "愿意开始，需要陪伴感和节奏确认。",
        "response_goal": "确认可以慢慢来，不要求一次讲完整。",
        "tone": "陪伴、温和、低压力",
        "sample_sentences": [
            "那我们就慢慢来，不急着讲完整。",
            "您想到哪里，我就帮您记到哪里。",
            "可以先从一个小画面或一个人开始。",
        ],
        "response": "那我们就慢慢来，不急着讲完整。您想到哪里，我就帮您记到哪里。",
    },
    "emotional_memory": {
        "card_label": "有些回忆让我有点感慨",
        "scene": "用户愿意聊，但回忆触发了较多情绪。",
        "user_state": "有情绪波动，需要被承接和尊重边界。",
        "response_goal": "先共情，再提醒用户只讲愿意讲的部分。",
        "tone": "温柔、克制、尊重",
        "sample_sentences": [
            "有些回忆一想起来确实会有很多感受。",
            "您只讲愿意留下的部分就好。",
            "如果某段不想说，我们可以随时换一个轻一点的话题。",
        ],
        "response": "有些回忆一想起来确实会有很多感受。您只讲愿意留下的部分就好，我会帮您好好记录。",
    },
    "unknown_process": {
        "card_label": "我不太了解采访会怎么进行",
        "scene": "用户第一次进入采访，不确定接下来会发生什么。",
        "user_state": "对流程不确定，担心自己不知道如何配合。",
        "response_goal": "用简单语言说明采访像聊天一样进行，降低未知感。",
        "tone": "清晰、温和、低压力",
        "sample_sentences": [
            "方式很简单，我会像聊天一样问几个小问题。",
            "您不用提前准备，也不用一次讲完整。",
            "如果有问题不想回答，可以跳过。",
        ],
        "response": "方式很简单，我会像聊天一样一次只问一个小问题。您不用提前准备，也不用一次讲完整。",
    },
    "restrained": {
        "card_label": "我不太习惯表达，怕讲不好",
        "scene": "用户担心自己表达不清楚、讲得乱或讲不好。",
        "user_state": "表达信心不足，需要降低表达压力。",
        "response_goal": "明确告诉用户零散表达也可以，不要求完整或漂亮。",
        "tone": "接纳、鼓励、轻松",
        "sample_sentences": [
            "讲得零散也没有关系。",
            "您说几个词、几句话，我也能帮您慢慢整理。",
            "不用特意组织语言，想到什么就说什么。",
        ],
        "response": "讲得零散也没有关系。您说几个词、几句话，我也能帮您慢慢整理成故事。",
    },
    "enthusiastic": {
        "card_label": "我愿意分享，可以直接聊",
        "scene": "用户参与度高，愿意快速进入采访。",
        "user_state": "准备度高，可以进入正式采访。",
        "response_goal": "快速承接热情，并给出一个低门槛开场点。",
        "tone": "积极、稳妥、自然",
        "sample_sentences": [
            "太好了，那我们可以直接开始。",
            "可以先从您最想被家人记住的一段经历说起。",
            "也可以从小时候的一个画面开始。",
        ],
        "response": "太好了，那我们可以直接开始。可以先从您最想被家人记住的一段经历说起，或从小时候的一个画面开始。",
    },
    "scattered": {
        "card_label": "我思绪有点乱，不知道从哪里说起",
        "scene": "用户愿意开始，但不知道选择哪段经历作为入口。",
        "user_state": "需要结构化入口和选择权。",
        "response_goal": "告诉用户不必按时间顺序，提供人、地点、事件等入口。",
        "tone": "耐心、引导式、不催促",
        "sample_sentences": [
            "我们可以不用按顺序来。",
            "可以从一个人、一个地方，或一件现在还记得的小事开始。",
            "您只要说最先想到的部分，后面我会帮您慢慢整理。",
        ],
        "response": "我们可以不用按顺序来。您可以从一个人、一个地方，或一件现在还记得的小事开始。",
    },
    "worry_privacy": {
        "card_label": "我担心有些内容不方便说",
        "scene": "用户担心隐私、边界或不想讲某些内容。",
        "user_state": "有安全顾虑，需要确认自己拥有选择权。",
        "response_goal": "明确用户可以跳过不想说的内容，建立边界感和控制感。",
        "tone": "尊重、克制、可靠",
        "sample_sentences": [
            "不方便说的内容可以直接跳过。",
            "您只需要讲愿意留下的部分。",
            "如果聊到不想说的地方，我们就换一个轻松的话题。",
        ],
        "response": "不方便说的内容可以直接跳过。您只需要讲愿意留下的部分，遇到不想说的地方我们就换个话题。",
    },
}

CARD_ID_ALIASES = {
    "need_more_guidance": "need_guidance",
    "dont_know_process": "unknown_process",
    "dont_know_start_point": "scattered",
    "worry_not_good_at_talking": "restrained",
    "want_example_first": "unknown_process",
}


def normalize_card_id(card_id: str) -> str:
    return CARD_ID_ALIASES.get(card_id, card_id)
