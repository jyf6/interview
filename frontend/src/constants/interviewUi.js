export const ENTRY_CARDS = [
  { card_id: 'start_interview', label: '直接开始采访' },
  { card_id: 'need_guidance', label: '我还有点顾虑' },
]

export const GUIDANCE_CARDS = [
  { card_id: 'relaxed_slow', label: '我想放松一点，慢慢回忆' },
  { card_id: 'emotional_memory', label: '有些回忆让我有点感触' },
  { card_id: 'unknown_process', label: '我不太了解采访会怎么进行' },
  { card_id: 'restrained', label: '我不太习惯表达，怕讲不好' },
  { card_id: 'enthusiastic', label: '我愿意分享，可以直接聊' },
  { card_id: 'scattered', label: '我思绪有点乱，不知道从哪里说起' },
  { card_id: 'custom_question', label: '我想自己提一个问题' },
]

export const ONBOARDING_GUIDE = {
  guide_id: 'interview-dialog-onboarding',
  version: '1.0.0',
  title: '采访助手使用引导',
  steps: [
    {
      step_id: 'chat_panel',
      sequence: 1,
      title: '这里是对话区',
      body: '开场白、安抚回复、采访问题和你的选择都会按聊天形式展示在这里。',
      target_key: 'chat_panel',
      placement: 'center',
      primary_action_label: '知道了',
    },
    {
      step_id: 'entry_cards',
      sequence: 2,
      title: '选择如何开始',
      body: '直接开始会进入正式采访；如果还没想好，可以先通过引导卡片慢慢准备。',
      target_key: 'card_options',
      placement: 'top',
      primary_action_label: '下一步',
    },
    {
      step_id: 'composer',
      sequence: 3,
      title: '在这里发送回答',
      body: '进入正式采访后，底部输入框会解锁。输入内容后发送，AI 会按当前采访阶段继续追问。',
      target_key: 'composer',
      placement: 'top',
      primary_action_label: '下一步',
    },
    {
      step_id: 'reset',
      sequence: 4,
      title: '可以重新开始',
      body: '如果想重新体验开场白和卡片流程，可以点击这里创建一轮新的会话。',
      target_key: 'reset_button',
      placement: 'bottom',
      primary_action_label: '下一步',
    },
    {
      step_id: 'skip',
      sequence: 5,
      title: '随时退出引导',
      body: '点击引导外层或“跳过”即可关闭说明，不会影响当前采访会话。',
      target_key: 'guide_skip_button',
      placement: 'top',
      primary_action_label: '完成',
    },
  ],
}

export const STATE_STEPS = [
  { value: 'INIT', label: '初始化' },
  { value: 'OPENING_GENERATING', label: '生成开场白' },
  { value: 'OPENING_DELIVERED', label: '开场完成' },
  { value: 'GUIDANCE_CARD', label: '引导卡片' },
  { value: 'READY_TO_INTERVIEW', label: '准备采访' },
  { value: 'INTERVIEWING', label: '采访中' },
  { value: 'end', label: '采访结束' },
]

export const INTERVIEW_STAGES = [
  {
    id: 'S1',
    title: '童年时光',
    description: '围绕出生环境、家人、玩伴、童年小事和儿时心愿慢慢展开。',
  },
  {
    id: 'S2',
    title: '青春岁月',
    description: '聊求学、离家、初入社会、朋友陪伴、理想和年轻时的打拼。',
  },
  {
    id: 'S3',
    title: '人生转折',
    description: '进入成家、择业、重大选择、责任、困境和低谷等关键经历。',
  },
  {
    id: 'S4',
    title: '岁月阅历',
    description: '回看半生感悟、当下生活、心态变化和日常里的小幸福。',
  },
  {
    id: 'S5',
    title: '收尾总结',
    description: '逐步收束采访，聊遗憾、释怀、人生总结和想留下的话。',
  },
]

export const MESSAGE_ROLE_LABELS = {
  assistant: '记',
  user: '我',
  system: '引',
}
