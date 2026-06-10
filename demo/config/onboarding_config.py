"""
产品入场引导配置。

后端只描述「引导语义」和「目标 key」，不绑定具体前端 DOM。
接入方根据 target_contract 将 target_key 映射到自己的按钮、输入框或页面区域。
"""

ONBOARDING_GUIDE = {
    "guide_id": "silver_bio_entry_guide",
    "version": "0.1.0",
    "title": "开始前，先熟悉一下怎么用",
    "description": "五个小提示帮助用户理解采访流程、发送方式和退出方式。",
    "target_contract": {
        "page_root": "产品主页面或聊天容器",
        "start_interview_button": "开始会话/开始采访入口",
        "guidance_button": "需要帮助、不知道怎么说或引导卡片入口",
        "message_composer": "用户输入框和发送按钮区域",
        "exit_button": "退出、结束、关闭或重置入口",
    },
    "steps": [
        {
            "step_id": "welcome",
            "sequence": 1,
            "title": "这里是传记采访助手",
            "body": "我会用聊天的方式陪您回忆经历，您不用提前准备，想到哪里说到哪里就好。",
            "target_key": "page_root",
            "placement": "center",
            "primary_action_label": "我知道了",
        },
        {
            "step_id": "start_interview",
            "sequence": 2,
            "title": "从这里开始采访",
            "body": "点击「开始会话」后，系统会先给出一段温和的开场白，再进入采访流程。",
            "target_key": "start_interview_button",
            "placement": "top",
            "primary_action_label": "下一步",
        },
        {
            "step_id": "ask_for_guidance",
            "sequence": 3,
            "title": "没想好也可以先点引导",
            "body": "如果一时不知道从哪里说起，可以点击引导入口，选择更符合当前状态的提示卡片。",
            "target_key": "guidance_button",
            "placement": "top",
            "primary_action_label": "下一步",
        },
        {
            "step_id": "send_message",
            "sequence": 4,
            "title": "在这里输入并发送",
            "body": "把想讲的内容输入到文本框，点击「发送」即可；在测试页里也可以按 Enter 发送。",
            "target_key": "message_composer",
            "placement": "top",
            "primary_action_label": "下一步",
        },
        {
            "step_id": "exit_product",
            "sequence": 5,
            "title": "需要离开时从这里退出",
            "body": "采访可以随时停下。点击退出或重置入口后，当前页面会回到初始状态，后续可继续接入保存与恢复能力。",
            "target_key": "exit_button",
            "placement": "top",
            "primary_action_label": "完成",
        },
    ],
}
