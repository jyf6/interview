<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  getInterviewState,
  getUserInfo,
  saveUserInfo,
  sendDialogAction,
  sendDialogText,
  startDialog,
  streamOpening,
} from './api/interview'

const ENTRY_CARDS = [
  { card_id: 'start_interview', label: '直接开始采访' },
  { card_id: 'need_guidance', label: '我还有点顾虑' },
]

const GUIDANCE_CARDS = [
  { card_id: 'relaxed_slow', label: '我想放松一点，慢慢回忆' },
  { card_id: 'emotional_memory', label: '有些回忆让我有点感慨' },
  { card_id: 'unknown_process', label: '我不太了解采访会怎么进行' },
  { card_id: 'restrained', label: '我不太习惯表达，怕讲不好' },
  { card_id: 'enthusiastic', label: '我愿意分享，可以直接聊' },
  { card_id: 'scattered', label: '我思绪有点乱，不知道从哪里说起' },
  { card_id: 'custom_question', label: '我想自己提一个问题' },
]

const ONBOARDING_GUIDE = {
  guide_id: 'interview-dialog-onboarding',
  version: '1.0.0',
  title: '采访助手使用引导',
  steps: [
    { step_id: 'chat_panel', sequence: 1, title: '这里是对话区', body: '开场白、安抚回复、采访问题和你的选择都会按聊天形式展示在这里。', target_key: 'chat_panel', placement: 'center', primary_action_label: '知道了' },
    { step_id: 'entry_cards', sequence: 2, title: '选择如何开始', body: '点击“直接开始采访”会进入正式采访；如果还没想好，可以先点击引导卡片慢慢准备。', target_key: 'card_options', placement: 'top', primary_action_label: '下一步' },
    { step_id: 'composer', sequence: 3, title: '在这里发送回答', body: '进入正式采访后，底部输入框会解锁。输入内容后点击发送，AI 会按当前采访阶段继续追问。', target_key: 'composer', placement: 'top', primary_action_label: '下一步' },
    { step_id: 'reset', sequence: 4, title: '可以重新开始', body: '如果想重新体验开场白和卡片流程，可以点击这里创建一轮新的会话。', target_key: 'reset_button', placement: 'bottom', primary_action_label: '下一步' },
    { step_id: 'skip', sequence: 5, title: '随时退出引导', body: '点击引导外层或“跳过”即可关闭说明，不会影响当前采访会话。', target_key: 'guide_skip_button', placement: 'top', primary_action_label: '完成' },
  ],
}

const loading = ref(false)
const error = ref('')
const userId = ref('demo-user')
const sessionId = ref('')
const currentState = ref('INIT')
const previousState = ref('')
const cardGroup = ref('none')
const responseSource = ref('none')
const guidanceRound = ref(0)
const maxGuidanceRounds = ref(3)
const interviewState = ref({})
const cards = ref([])
const messages = ref([])
const streamingOpening = ref('')
const inputText = ref('')
const customQuestion = ref('')
const customQuestionOpen = ref(false)
const chatArea = ref(null)
const statePolling = ref(false)
const pollTimer = ref(null)
const userInfoSaving = ref(false)
const userInfoSavedAt = ref('')
const userInfoForm = ref({
  name: '',
  gender: '',
  age: '',
  last_used_at: '',
})

const onboardingGuide = ref(null)
const onboardingActive = ref(false)
const onboardingIndex = ref(0)
const targetRect = ref(null)

const stateSteps = [
  { value: 'INIT', label: '初始化' },
  { value: 'OPENING_GENERATING', label: '生成开场白' },
  { value: 'OPENING_DELIVERED', label: '开场完成' },
  { value: 'GUIDANCE_CARD', label: '引导卡片' },
  { value: 'READY_TO_INTERVIEW', label: '准备采访' },
  { value: 'INTERVIEWING', label: '采访中' },
  { value: 'end', label: '采访结束' },
]

const interviewStages = [
  {
    id: 'S1',
    title: '童年时光',
    description: '围绕出生环境、家人、玩伴、童年小事和儿时心愿慢慢展开。',
  },
  {
    id: 'S2',
    title: '青春岁月',
    description: '聊求学、离家、初入社会、朋友陪伴、理想和年少打拼。',
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

const stateText = computed(() => currentState.value || 'INIT')
const stateLabel = computed(() => stateSteps.find((item) => item.value === stateText.value)?.label ?? stateText.value)
const currentStateIndex = computed(() => stateSteps.findIndex((item) => item.value === stateText.value))
const roundText = computed(() => `${guidanceRound.value}/${maxGuidanceRounds.value}`)
const interviewStageText = computed(() => interviewState.value?.stage_id ?? '-')
const activeInterviewStage = computed(() => {
  return interviewStages.find((item) => item.id === interviewStageText.value) ?? null
})
const interviewStageTitle = computed(() => activeInterviewStage.value?.title ?? '未进入采访阶段')
const interviewStageDescription = computed(() => {
  return activeInterviewStage.value?.description ?? '开始采访后，这里会显示当前所处阶段和采访节奏。'
})
const activeStageFlowEntry = computed(() => {
  const flow = Array.isArray(interviewState.value?.stage_flow) ? interviewState.value.stage_flow : []
  return flow.find((item) => item?.stage_id === interviewStageText.value) ?? null
})
const interviewStageCompletedCount = computed(() => {
  const completedIds = Array.isArray(activeStageFlowEntry.value?.completed_main_question_ids)
    ? activeStageFlowEntry.value.completed_main_question_ids
    : Array.isArray(interviewState.value?.completed_main_question_ids)
      ? interviewState.value.completed_main_question_ids
      : []
  return completedIds.length
})
const interviewAwaitingStageCompletion = computed(() => String(interviewState.value?.awaiting_stage_completion ?? 0) === '1')
const interviewCompletedText = computed(() => String(interviewState.value?.completed ?? 0) === '1' ? '已完成' : '进行中')
const interviewStageProgressText = computed(() => {
  if (interviewCompletedText.value === '已完成') return '采访已完成'
  if (interviewAwaitingStageCompletion.value) return '本阶段主问题已收集完成，等待补充收尾'
  if (interviewStageCompletedCount.value > 0) return `本阶段已收集 ${interviewStageCompletedCount.value} 个主问题`
  return '本阶段主问题逐步推进中'
})
const interviewStageStatusText = computed(() => {
  if (interviewCompletedText.value === '已完成') return '已完成'
  if (!activeInterviewStage.value) return '待开始'
  if (interviewAwaitingStageCompletion.value) return '等待收尾'
  return '进行中'
})
const canType = computed(() => currentState.value === 'READY_TO_INTERVIEW' || currentState.value === 'INTERVIEWING')
const cardsTitle = computed(() => {
  if (cardGroup.value === 'guidance') return '选择一个最接近的感受'
  if (cardGroup.value === 'entry') return '请选择下一步'
  return ''
})
const activeStep = computed(() => onboardingGuide.value?.steps?.[onboardingIndex.value] ?? null)
const onboardingProgress = computed(() => {
  const total = onboardingGuide.value?.steps?.length ?? 0
  return total ? `${onboardingIndex.value + 1}/${total}` : ''
})
const highlightStyle = computed(() => {
  if (!onboardingActive.value || !targetRect.value) return { display: 'none' }
  return {
    top: `${targetRect.value.top - 6}px`,
    left: `${targetRect.value.left - 6}px`,
    width: `${targetRect.value.width + 12}px`,
    height: `${targetRect.value.height + 12}px`,
  }
})
const popoverStyle = computed(() => {
  if (!onboardingActive.value || !activeStep.value || !targetRect.value) {
    return { top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }
  }

  const rect = targetRect.value
  const width = Math.min(360, window.innerWidth - 32)
  const left = clamp(rect.left + rect.width / 2 - width / 2, 16, window.innerWidth - width - 16)
  let top = rect.bottom + 16

  if (activeStep.value.placement === 'top') top = rect.top - 188
  if (activeStep.value.placement === 'center') top = window.innerHeight / 2 - 120
  if (activeStep.value.placement === 'bottom') top = rect.bottom + 16

  return {
    width: `${width}px`,
    top: `${clamp(top, 16, window.innerHeight - 220)}px`,
    left: `${left}px`,
  }
})

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max)
}

function appendMessage(role, content) {
  if (!content) return
  messages.value.push({
    id: `${Date.now()}-${messages.value.length}`,
    role,
    content,
  })
  scrollToBottom()
}

function scrollToBottom() {
  nextTick(() => {
    if (chatArea.value) {
      chatArea.value.scrollTop = chatArea.value.scrollHeight
    }
  })
}

function applyTurn(data) {
  sessionId.value = data.session_id
  currentState.value = data.current_state
  previousState.value = data.previous_state || ''
  cardGroup.value = data.card_group ?? cardGroup.value
  responseSource.value = data.response_source
  guidanceRound.value = data.guidance_round
  maxGuidanceRounds.value = data.max_guidance_rounds
  interviewState.value = data.state_interview || interviewState.value || {}
  if (data.cards?.length) {
    cards.value = data.cards
  } else if (data.action === 'show_guidance_cards') {
    cards.value = [...GUIDANCE_CARDS]
  }

  if (data.message?.content) {
    appendMessage(data.message.role || 'assistant', data.message.content)
  }

  if (data.action === 'ready_to_interview') {
    appendMessage('system', '已准备进入采访，可以开始自由回答。')
  }

  refreshOnboardingTarget()
}

function applyUserInfo(data) {
  const info = data?.userinfo ?? {}
  userInfoForm.value = {
    name: info.name ?? '',
    gender: info.gender ?? '',
    age: info.age ?? '',
    last_used_at: info.last_used_at ?? '',
  }
}

async function run(actionFn) {
  loading.value = true
  error.value = ''
  try {
    await actionFn()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '请求失败'
    appendMessage('system', `请求失败：${error.value}`)
  } finally {
    loading.value = false
    refreshOnboardingTarget()
  }
}

function startOnboardingGuide() {
  const guide = ONBOARDING_GUIDE
  onboardingGuide.value = {
    ...guide,
    steps: [...guide.steps].sort((a, b) => a.sequence - b.sequence),
  }
  onboardingActive.value = true
  onboardingIndex.value = 0
  refreshOnboardingTarget()
}

async function resetDialog() {
  await run(async () => {
    stopStatePolling()
    sessionId.value = ''
    currentState.value = 'INIT'
    previousState.value = ''
    cardGroup.value = 'none'
    responseSource.value = 'none'
    interviewState.value = {}
    guidanceRound.value = 0
    maxGuidanceRounds.value = 3
    cards.value = []
    messages.value = []
    streamingOpening.value = ''
    userInfoSavedAt.value = ''
    appendMessage('system', '正在准备采访开场...')
    const data = await startDialog(null, userId.value.trim())
    applyTurn(data)
    await loadUserInfo()
    startStatePolling()
    // 流式获取开场白
    await streamOpening(data.session_id, userId.value.trim(), {
      onToken: (_token, fullText) => {
        streamingOpening.value = fullText
        scrollToBottom()
      },
      onComplete: (fullText) => {
        streamingOpening.value = ''
        appendMessage('assistant', fullText)
        cards.value = [...ENTRY_CARDS]
        cardGroup.value = 'entry'
      },
    })
  })
}

async function simulateResumeDialog() {
  if (!sessionId.value || loading.value || currentState.value !== 'INTERVIEWING') return
  await run(async () => {
    stopStatePolling()
    cards.value = []
    cardGroup.value = 'none'
    customQuestionOpen.value = false
    appendMessage('system', '已模拟离开页面，现在使用同一个会话重新进入。')
    const data = await startDialog(sessionId.value, userId.value.trim())
    applyTurn(data)
    await refreshState()
    startStatePolling()
  })
}

async function chooseCard(card) {
  if (!sessionId.value || loading.value) return
  if (card.card_id === 'custom_question') {
    customQuestionOpen.value = true
    return
  }
  appendMessage('user', card.label)
  cards.value = []
  await run(async () => {
    const data = await sendDialogAction({
      session_id: sessionId.value,
      card_id: card.card_id,
    })
    applyTurn(data)
    await refreshState()
  })
}

async function sendCustomQuestion() {
  const question = customQuestion.value.trim()
  if (!sessionId.value || !question || loading.value) return
  appendMessage('user', question)
  customQuestion.value = ''
  customQuestionOpen.value = false
  cards.value = []
  await run(async () => {
    const data = await sendDialogAction({
      session_id: sessionId.value,
      card_id: 'custom_question',
      question,
    })
    applyTurn(data)
    await refreshState()
  })
}

async function sendText() {
  const text = inputText.value.trim()
  if (!text) return
  appendMessage('user', text)
  inputText.value = ''
  await run(async () => {
    const data = await sendDialogText({
      session_id: sessionId.value,
      content: text,
    })
    applyTurn(data)
    await refreshState()
  })
}

async function refreshState() {
  if (!sessionId.value) return
  try {
    statePolling.value = true
    const data = await getInterviewState(sessionId.value)
    currentState.value = data.state || currentState.value
    interviewState.value = data.state_interview || interviewState.value || {}
  } catch (err) {
    console.warn('Failed to refresh interview state', err)
  } finally {
    statePolling.value = false
  }
}

function startStatePolling() {
  stopStatePolling()
  if (!sessionId.value) return
  pollTimer.value = window.setInterval(refreshState, 1500)
}

function stopStatePolling() {
  if (!pollTimer.value) return
  window.clearInterval(pollTimer.value)
  pollTimer.value = null
}

async function loadUserInfo() {
  const id = userId.value.trim()
  if (!id) return
  try {
    const data = await getUserInfo(id)
    applyUserInfo(data)
  } catch (err) {
    console.warn('Failed to load user info', err)
  }
}

function buildUserInfoPayload() {
  return {
    name: userInfoForm.value.name.trim(),
    gender: userInfoForm.value.gender.trim(),
    age: userInfoForm.value.age.trim(),
    last_used_at: userInfoForm.value.last_used_at.trim(),
  }
}

async function submitUserInfo() {
  const id = userId.value.trim()
  if (!id || userInfoSaving.value) return
  userInfoSaving.value = true
  error.value = ''
  try {
    const data = await saveUserInfo(id, buildUserInfoPayload())
    applyUserInfo(data)
    userInfoSavedAt.value = new Date().toLocaleTimeString()
    await refreshState()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '用户信息保存失败'
  } finally {
    userInfoSaving.value = false
  }
}

function getTargetElement(targetKey) {
  if (!targetKey) return null
  return document.querySelector(`[data-onboarding-target="${targetKey}"]`)
}

function refreshOnboardingTarget() {
  nextTick(() => {
    if (!onboardingActive.value || !activeStep.value) return
    const element = getTargetElement(activeStep.value.target_key)
    targetRect.value = element ? element.getBoundingClientRect() : null
  })
}

function nextOnboardingStep() {
  const total = onboardingGuide.value?.steps?.length ?? 0
  if (onboardingIndex.value + 1 >= total) {
    closeOnboarding()
    return
  }
  onboardingIndex.value += 1
  refreshOnboardingTarget()
}

function closeOnboarding() {
  onboardingActive.value = false
  targetRect.value = null
}

function handleWindowChange() {
  refreshOnboardingTarget()
}

watch(sessionId, async (value) => {
  if (!value) {
    stopStatePolling()
    return
  }
  await refreshState()
  startStatePolling()
})

watch(userId, async (value) => {
  userInfoSavedAt.value = ''
  if (value.trim()) {
    await loadUserInfo()
  }
})

onMounted(async () => {
  window.addEventListener('resize', handleWindowChange)
  window.addEventListener('scroll', handleWindowChange, true)
  await resetDialog()
  await startOnboardingGuide()
})

onBeforeUnmount(() => {
  stopStatePolling()
  window.removeEventListener('resize', handleWindowChange)
  window.removeEventListener('scroll', handleWindowChange, true)
})
</script>

<template>
  <main class="app-shell">
    <div class="workspace">
      <section class="chat-panel" data-onboarding-target="chat_panel">
        <header class="chat-header">
          <div>
            <p class="eyebrow">Interview Guidance</p>
            <h1>传记采访引导</h1>
          </div>
          <div class="header-actions">
            <button
              class="icon-button"
              type="button"
              :disabled="loading || !sessionId || currentState !== 'INTERVIEWING'"
              title="模拟用户退出后再次回来"
              @click="simulateResumeDialog"
            >
              模拟重进
            </button>
            <button
              class="icon-button"
              type="button"
              :disabled="loading"
              title="重新开始"
              data-onboarding-target="reset_button"
              @click="resetDialog"
            >
              重新开始
            </button>
          </div>
        </header>

        <section class="interview-stage-banner" aria-label="当前采访状态">
          <div class="stage-main">
            <span class="stage-code">{{ interviewStageText }}</span>
            <div>
              <p class="eyebrow">当前采访状态</p>
              <h2>{{ interviewStageTitle }}</h2>
            </div>
          </div>
          <p>{{ interviewStageDescription }}</p>
          <div class="stage-meta">
            <span>{{ interviewStageStatusText }}</span>
            <span>{{ interviewStageProgressText }}</span>
            <span>流程状态：{{ stateLabel }}</span>
            <span>来源：{{ responseSource }}</span>
          </div>
        </section>

        <div v-if="error" class="error-box">
          {{ error }}
        </div>

        <section class="user-id-bar">
          <label>
            <span>用户 ID</span>
            <input v-model="userId" type="text" placeholder="请输入用户唯一 ID" :disabled="loading" />
          </label>
          <button type="button" :disabled="loading || !userId.trim()" @click="resetDialog">使用该用户开始</button>
        </section>

        <section ref="chatArea" class="chat-area">
          <article v-for="message in messages" :key="message.id" class="message-row" :class="message.role">
            <div class="avatar">
              {{ message.role === 'assistant' ? '记' : message.role === 'user' ? '我' : '引' }}
            </div>
            <div class="bubble">
              {{ message.content }}
            </div>
          </article>

          <article v-if="loading && !streamingOpening" class="message-row assistant">
            <div class="avatar">记</div>
            <div class="bubble thinking">正在思考...</div>
          </article>

          <article v-if="streamingOpening" class="message-row assistant">
            <div class="avatar">记</div>
            <div class="bubble streaming">{{ streamingOpening }}<span class="cursor">▌</span></div>
          </article>
        </section>

        <section v-if="cards.length" class="cards-section" data-onboarding-target="card_options">
          <h2>{{ cardsTitle }}</h2>
          <div class="cards-grid" :class="cardGroup">
            <button
              v-for="card in cards"
              :key="card.card_id"
              class="card-button"
              type="button"
              :disabled="loading"
              @click="chooseCard(card)"
            >
              {{ card.label }}
            </button>
          </div>
          <form v-if="customQuestionOpen" class="custom-question" @submit.prevent="sendCustomQuestion">
            <input v-model="customQuestion" type="text" placeholder="请输入你想问的问题" />
            <button type="submit" :disabled="!customQuestion.trim() || loading">提问</button>
          </form>
        </section>

        <form class="composer" data-onboarding-target="composer" @submit.prevent="sendText">
          <input
            v-model="inputText"
            type="text"
            :disabled="!canType || loading"
            :placeholder="canType ? '输入你的回答...' : '请先通过卡片完成采访前引导'"
          />
          <button type="submit" :disabled="!canType || loading || !inputText.trim()">发送</button>
        </form>
      </section>

      <aside class="side-panel">
        <section class="status-panel">
          <div class="panel-heading">
            <div>
              <p class="eyebrow">State Machine</p>
              <h2>流程状态</h2>
            </div>
            <span class="live-pill" :class="{ polling: statePolling }">
              {{ statePolling ? '同步中' : '实时' }}
            </span>
          </div>

          <div class="state-summary">
            <span class="state-code">{{ stateText }}</span>
            <strong>{{ stateLabel }}</strong>
            <small>Session：{{ sessionId || '-' }}</small>
            <small>User ID：{{ userId || '-' }}</small>
          </div>

          <div class="stage-summary">
            <div>
              <span class="stage-code">{{ interviewStageText }}</span>
              <strong>{{ interviewStageTitle }}</strong>
            </div>
            <p>{{ interviewStageDescription }}</p>
            <small>{{ interviewCompletedText }} · {{ interviewStageProgressText }}</small>
          </div>

          <ol class="state-timeline">
            <li
              v-for="(step, index) in stateSteps"
              :key="step.value"
              :class="{
                active: step.value === stateText,
                complete: currentStateIndex > index,
              }"
            >
              <span class="state-dot"></span>
              <div>
                <strong>{{ step.label }}</strong>
                <small>{{ step.value }}</small>
              </div>
            </li>
          </ol>
        </section>

        <section class="userinfo-panel">
          <div class="panel-heading">
            <div>
              <p class="eyebrow">User Info</p>
              <h2>用户信息</h2>
            </div>
            <span v-if="userInfoSavedAt" class="saved-text">已保存 {{ userInfoSavedAt }}</span>
          </div>

          <form class="userinfo-form" @submit.prevent="submitUserInfo">
            <label>
              <span>姓名</span>
              <input v-model="userInfoForm.name" type="text" placeholder="例如：王阿姨" />
            </label>
            <label>
              <span>性别</span>
              <input v-model="userInfoForm.gender" type="text" placeholder="例如：女 / 男 / 未知" />
            </label>
            <label>
              <span>年龄</span>
              <input v-model="userInfoForm.age" type="text" placeholder="例如：72" />
            </label>
            <label>
              <span>上次使用时间</span>
              <input v-model="userInfoForm.last_used_at" type="text" placeholder="例如：2026-06-10T18:30:00" />
            </label>
            <button type="submit" :disabled="!userId.trim() || userInfoSaving">
              {{ userInfoSaving ? '保存中...' : '保存用户信息' }}
            </button>
          </form>
        </section>
      </aside>
    </div>

    <div v-if="onboardingActive && activeStep" class="onboarding-layer" aria-live="polite">
      <button class="onboarding-backdrop" type="button" aria-label="关闭引导" @click="closeOnboarding"></button>
      <div class="onboarding-highlight" :style="highlightStyle"></div>
      <section class="onboarding-popover" :style="popoverStyle">
        <div class="onboarding-meta">
          <span>{{ onboardingGuide.title }}</span>
          <span>{{ onboardingProgress }}</span>
        </div>
        <h2>{{ activeStep.title }}</h2>
        <p>{{ activeStep.body }}</p>
        <div class="onboarding-actions">
          <button
            type="button"
            class="text-button"
            data-onboarding-target="guide_skip_button"
            @click="closeOnboarding"
          >
            跳过
          </button>
          <button type="button" class="primary-button" @click="nextOnboardingStep">
            {{ activeStep.primary_action_label }}
          </button>
        </div>
      </section>
    </div>
  </main>
</template>
