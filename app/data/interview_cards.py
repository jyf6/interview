ENTRY_CARDS = [
    {
        "card_id": "start_interview",
        "label": "直接开始采访",
    },
    {
        "card_id": "need_guidance",
        "label": "我还没想好怎么说",
    },
]

GUIDANCE_CARDS = [
    {
        "card_id": "dont_know_process",
        "label": "我不太了解采访会怎么进行",
    },
    {
        "card_id": "dont_know_start_point",
        "label": "我不知道从哪段经历开始",
    },
    {
        "card_id": "worry_not_good_at_talking",
        "label": "我不太会表达，怕讲不好",
    },
    {
        "card_id": "worry_privacy",
        "label": "我担心有些内容不方便说",
    },
    {
        "card_id": "want_example_first",
        "label": "我想先看一个例子",
    },
]

CARD_RESPONSE_CORPUS = {
    "dont_know_process": {
        "card_label": "我不太了解采访会怎么进行",
        "scene": "用户第一次进入采访，不确定接下来会发生什么。",
        "user_state": "对流程不确定，担心自己不知道该如何配合。",
        "response_goal": "用简单语言说明采访像聊天一样进行，降低未知感。",
        "tone": "清晰、温和、低压力",
        "sample_sentences": [
            "采访会像聊天一样慢慢来，我会一次只问一个简单问题。",
            "您不用提前准备，想到多少说多少就可以。",
            "如果有问题不想回答，可以跳过，我们换一个轻松的话题。",
        ],
        "response": "采访会像聊天一样慢慢来，我一次只问一个简单问题。您不用提前准备，想到多少说多少就好。",
    },
    "dont_know_start_point": {
        "card_label": "我不知道从哪段经历开始",
        "scene": "用户愿意开始，但不知道选择哪段经历作为开头。",
        "user_state": "有表达意愿，但缺少叙事入口。",
        "response_goal": "告诉用户不用按时间顺序讲，可以从最容易想到的一点开始。",
        "tone": "耐心、引导式、不催促",
        "sample_sentences": [
            "回忆不一定要按顺序来。",
            "可以先从一个人、一个地方，或一件小事开始。",
            "您只要说最先想到的部分，后面我会帮您慢慢整理。",
        ],
        "response": "没关系，回忆不一定要按顺序来。可以先从一个人、一个地方，或一件最容易想到的小事开始。",
    },
    "worry_not_good_at_talking": {
        "card_label": "我不太会表达，怕讲不好",
        "scene": "用户担心自己表达不清楚、讲得乱、说不好。",
        "user_state": "表达信心不足，需要降低表达压力。",
        "response_goal": "明确告诉用户零散表达也可以，不要求讲得完整或漂亮。",
        "tone": "接纳、鼓励、轻松",
        "sample_sentences": [
            "讲得零散也没有关系。",
            "您不用特意组织语言，想到什么说什么就好。",
            "哪怕只是几个词、几句话，也可以作为开始。",
        ],
        "response": "讲得零散也没有关系，您不用特意组织语言。想到什么就说什么，几个词、几句话也可以作为开始。",
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
        "response": "不方便说的内容可以直接跳过。您只需要讲愿意留下的部分，遇到不想说的地方，我们就换一个轻松的话题。",
    },
    "want_example_first": {
        "card_label": "我想先看一个例子",
        "scene": "用户不知道回答应该是什么样，希望先获得示范。",
        "user_state": "需要一个可模仿的表达样板。",
        "response_goal": "给出短小、普通、不文学化的示例，让用户知道简单说也可以。",
        "tone": "具体、清晰、轻松",
        "sample_sentences": [
            "可以，我先给您一个很短的例子。",
            "比如可以这样说：我以前住过一个地方，那里让我印象很深。",
            "您不用照着说完整，只要从一个画面开始就可以。",
        ],
        "response": "可以，我先给您一个很短的例子：我以前住过一个地方，那里让我印象很深。您不用照着说完整，从一个画面开始就好。",
    },
    "need_guidance": {
        "card_label": "我还没想好怎么说",
        "scene": "用户还没有准备好开始采访，需要更低压力的引导。",
        "user_state": "仍然需要陪伴、解释或启动帮助。",
        "response_goal": "进一步降低开始难度，邀请用户先选择最接近的顾虑。",
        "tone": "耐心、陪伴、低压力",
        "sample_sentences": [
            "没关系，我们可以再慢一点。",
            "您不用马上讲故事，先选一个最接近的感受就可以。",
            "我会根据您的选择，把问题调整得更轻一点。",
        ],
        "response": "没关系，我们可以再慢一点。您不用马上讲故事，先选一个最接近现在感受的卡片就可以。",
    },
}

CARD_ID_ALIASES = {
    "need_more_guidance": "need_guidance",
}


def normalize_card_id(card_id: str) -> str:
    return CARD_ID_ALIASES.get(card_id, card_id)
