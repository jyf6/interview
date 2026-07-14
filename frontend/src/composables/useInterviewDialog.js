import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  getInterviewState,
  getUserInfo,
  saveUserInfo,
  sendDialogAction,
  sendDialogText,
  startDialog,
  streamOpening,
} from '../api/interview'
import { ENTRY_CARDS, GUIDANCE_CARDS, INTERVIEW_STAGES, STATE_STEPS } from '../constants/interviewUi'

export function useInterviewDialog() {
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

  const stateText = computed(() => currentState.value || 'INIT')
  const stateLabel = computed(() => STATE_STEPS.find((item) => item.value === stateText.value)?.label ?? stateText.value)
  const currentStateIndex = computed(() => STATE_STEPS.findIndex((item) => item.value === stateText.value))
  const roundText = computed(() => `${guidanceRound.value}/${maxGuidanceRounds.value}`)
  const interviewStageText = computed(() => interviewState.value?.stage_id ?? '-')
  const activeInterviewStage = computed(() => {
    return INTERVIEW_STAGES.find((item) => item.id === interviewStageText.value) ?? null
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
  const interviewCompletedText = computed(() => (String(interviewState.value?.completed ?? 0) === '1' ? '已完成' : '进行中'))
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

  function appendMessage(role, content) {
    if (!content) return
    messages.value.push({
      id: `${Date.now()}-${messages.value.length}`,
      role,
      content,
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
    }
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
      await streamOpening(data.session_id, userId.value.trim(), {
        onToken: (_token, fullText) => {
          streamingOpening.value = fullText
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

  function updateUserInfoField(field, value) {
    userInfoForm.value = {
      ...userInfoForm.value,
      [field]: value,
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

  onBeforeUnmount(stopStatePolling)

  return {
    loading,
    error,
    userId,
    sessionId,
    currentState,
    cardGroup,
    responseSource,
    guidanceRound,
    maxGuidanceRounds,
    cards,
    messages,
    streamingOpening,
    inputText,
    customQuestion,
    customQuestionOpen,
    statePolling,
    userInfoSaving,
    userInfoSavedAt,
    userInfoForm,
    stateText,
    stateLabel,
    currentStateIndex,
    roundText,
    interviewStageText,
    interviewStageTitle,
    interviewStageDescription,
    interviewCompletedText,
    interviewStageProgressText,
    interviewStageStatusText,
    canType,
    cardsTitle,
    resetDialog,
    simulateResumeDialog,
    chooseCard,
    sendCustomQuestion,
    sendText,
    refreshState,
    updateUserInfoField,
    submitUserInfo,
  }
}
