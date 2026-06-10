from app.schemas.interview import OnboardingGuideResponse, OnboardingStep


class OnboardingService:
    def build_guide(self) -> OnboardingGuideResponse:
        return OnboardingGuideResponse(
            guide_id="interview-dialog-onboarding",
            version="1.0.0",
            title="采访助手使用引导",
            description="帮助用户理解开场白、卡片选择、引导卡片和正式采访入口。",
            steps=[
                OnboardingStep(
                    step_id="chat_panel",
                    sequence=1,
                    title="这里是对话区",
                    body="开场白、安抚回复和你的选择都会按聊天形式展示在这里。",
                    target_key="chat_panel",
                    placement="center",
                    primary_action_label="知道了",
                ),
                OnboardingStep(
                    step_id="entry_cards",
                    sequence=2,
                    title="先选择下一步",
                    body="你可以直接开始采访，也可以选择需要引导，让系统继续给出更细的帮助卡片。",
                    target_key="card_options",
                    placement="top",
                    primary_action_label="下一步",
                ),
                OnboardingStep(
                    step_id="composer",
                    sequence=3,
                    title="准备好后再输入",
                    body="完成采访前引导后，底部输入框会解锁，用来承接后续正式采访对话。",
                    target_key="composer",
                    placement="top",
                    primary_action_label="下一步",
                ),
                OnboardingStep(
                    step_id="reset",
                    sequence=4,
                    title="可以重新开始",
                    body="如果想重新体验开场白和卡片流程，可以从这里创建一轮新的会话。",
                    target_key="reset_button",
                    placement="bottom",
                    primary_action_label="完成",
                ),
            ],
            target_contract={
                "chat_panel": "聊天主容器，承载开场白、系统消息和用户消息。",
                "card_options": "卡片选项区域，承载入口卡片和二层引导卡片。",
                "composer": "底部输入区域，后续正式采访对话从这里继续。",
                "reset_button": "重新开始按钮，用于重置当前会话流程。",
            },
        )
