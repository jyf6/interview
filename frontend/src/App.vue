<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { sendDialogAction, startDialog } from './api/interview'

const FIXED_ONBOARDING_GUIDE = {
  guide_id: 'interview-dialog-onboarding',
  version: '1.0.0',
  title: '采访助手使用引导',
  description: '帮助用户理解开场白、卡片选择、引导卡片和正式采访入口。',
  steps: [
    {
      step_id: 'chat_panel',
      sequence: 1,
      title: '这里是对话区',
      body: '开场白、安抚回复和你的选择都会按聊天形式展示在这里。',
      target_key: 'chat_panel',
      placement: 'center',
      primary_action_label: '知道了',
    },
    {
      step_id: 'entry_cards',
      sequence: 2,
      title: '先选择下一步',
      body: '你可以直接开始采访，也可以选择需要引导，让系统继续给出更细的帮助卡片。',
      target_key: 'card_options',
      placement: 'top',
      primary_action_label: '下一步',
    },
    {
      step_id: 'composer',
      sequence: 3,
      title: '准备好后再输入',
      body: '完成采访前引导后，底部输入框会解锁，用来承接后续正式采访对话。',
      target_key: 'composer',
      placement: 'top',
      primary_action_label: '下一步',
    },
    {
      step_id: 'reset',
      sequence: 4,
      title: '可以重新开始',
      body: '如果想重新体验开场白和卡片流程，可以从这里创建一轮新的会话。',
      target_key: 'reset_button',
      placement: 'bottom',
      primary_action_label: '完成',
    },
  ],
}

const loading = ref(false)
const error = ref('')
const sessionId = ref('')
const currentState = ref('INIT')
const previousState = ref('')
const cardGroup = ref('none')
const responseSource = ref('none')
const guidanceRound = ref(0)
const maxGuidanceRounds = ref(3)
const cards = ref([])
const messages = ref([])
const inputText = ref('')
const chatArea = ref(null)

const onboardingGuide = ref(null)
const onboardingActive = ref(false)
const onboardingIndex = ref(0)
const targetRect = ref(null)

const stateText = computed(() => currentState.value || 'INIT')
const roundText = computed(() => `${guidanceRound.value}/${maxGuidanceRounds.value}`)
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
  cardGroup.value = data.card_group
  responseSource.value = data.response_source
  guidanceRound.value = data.guidance_round
  maxGuidanceRounds.value = data.max_guidance_rounds
  cards.value = data.cards || []

  if (data.message?.content) {
    appendMessage(data.message.role || 'assistant', data.message.content)
  }

  if (data.action === 'ready_to_interview') {
    appendMessage('system', '已准备进入采访，可以开始自由回答。')
  }

  refreshOnboardingTarget()
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
  onboardingGuide.value = FIXED_ONBOARDING_GUIDE
  onboardingActive.value = true
  onboardingIndex.value = 0
  refreshOnboardingTarget()
}

async function resetDialog() {
  await run(async () => {
    sessionId.value = ''
    currentState.value = 'INIT'
    previousState.value = ''
    cardGroup.value = 'none'
    responseSource.value = 'none'
    guidanceRound.value = 0
    maxGuidanceRounds.value = 3
    cards.value = []
    messages.value = []
    appendMessage('system', '正在准备采访开场...')
    const data = await startDialog()
    applyTurn(data)
  })
}

async function chooseCard(card) {
  if (!sessionId.value || loading.value) return
  appendMessage('user', card.label)
  cards.value = []
  await run(async () => {
    const data = await sendDialogAction({
      session_id: sessionId.value,
      card_id: card.card_id,
    })
    applyTurn(data)
  })
}

function sendText() {
  const text = inputText.value.trim()
  if (!text) return
  appendMessage('user', text)
  inputText.value = ''
  appendMessage('assistant', '这部分已经收到。正式采访智能体接入后，这里会继续追问、整理和生成采访内容。')
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

onMounted(async () => {
  window.addEventListener('resize', handleWindowChange)
  window.addEventListener('scroll', handleWindowChange, true)
  await resetDialog()
  startOnboardingGuide()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleWindowChange)
  window.removeEventListener('scroll', handleWindowChange, true)
})
</script>

<template>
  <main class="app-shell">
    <section class="chat-panel" data-onboarding-target="chat_panel">
      <header class="chat-header">
        <div>
          <p class="eyebrow">Interview Guidance</p>
          <h1>传记采访引导</h1>
        </div>
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
      </header>

      <div class="debug-strip">
        <span>状态：{{ stateText }}</span>
        <span>上一步：{{ previousState || '-' }}</span>
        <span>引导：{{ roundText }}</span>
        <span>来源：{{ responseSource }}</span>
      </div>

      <div v-if="error" class="error-box">
        {{ error }}
      </div>

      <section ref="chatArea" class="chat-area">
        <article v-for="message in messages" :key="message.id" class="message-row" :class="message.role">
          <div class="avatar">
            {{ message.role === 'assistant' ? '记' : message.role === 'user' ? '我' : '引' }}
          </div>
          <div class="bubble">
            {{ message.content }}
          </div>
        </article>

        <article v-if="loading" class="message-row assistant">
          <div class="avatar">记</div>
          <div class="bubble thinking">正在思考...</div>
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
          <button type="button" class="text-button" @click="closeOnboarding">跳过</button>
          <button type="button" class="primary-button" @click="nextOnboardingStep">
            {{ activeStep.primary_action_label }}
          </button>
        </div>
      </section>
    </div>
  </main>
</template>
