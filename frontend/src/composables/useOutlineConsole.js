import { ref } from 'vue'
import {
  createBiography,
  publishOutline,
  sendHighlightMessage,
  startHighlightSession,
  updateOutline,
} from '../api/interview'

export function useOutlineConsole(userId) {
  const biographyId = ref('')
  const highlightSessionId = ref('')
  const highlightMessages = ref([])
  const highlightInput = ref('')
  const highlightReady = ref(false)
  const outline = ref(null)
  const loading = ref(false)
  const error = ref('')

  async function startHighlight() {
    if (loading.value) return
    loading.value = true
    error.value = ''
    try {
      const biography = await createBiography(userId.value.trim() || null)
      biographyId.value = biography.id
      const turn = await startHighlightSession(biography.id)
      highlightSessionId.value = turn.session_id
      highlightMessages.value = turn.messages || []
      highlightReady.value = Boolean(turn.ready)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '高光采访启动失败'
    } finally {
      loading.value = false
    }
  }

  async function sendHighlight() {
    const content = highlightInput.value.trim()
    if (!content || !highlightSessionId.value || loading.value) return
    loading.value = true
    error.value = ''
    try {
      highlightInput.value = ''
      const turn = await sendHighlightMessage(biographyId.value, highlightSessionId.value, content)
      highlightMessages.value = turn.messages || highlightMessages.value
      highlightReady.value = Boolean(turn.ready)
      if (turn.outline) outline.value = turn.outline
    } catch (err) {
      error.value = err instanceof Error ? err.message : '高光采访发送失败'
    } finally {
      loading.value = false
    }
  }

  async function save() {
    if (!outline.value || loading.value) return
    loading.value = true
    error.value = ''
    try {
      outline.value = await updateOutline(outline.value.id, outline.value.chapters)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '大纲保存失败'
    } finally {
      loading.value = false
    }
  }

  async function publish() {
    if (!outline.value || loading.value) return
    loading.value = true
    error.value = ''
    try {
      outline.value = await publishOutline(outline.value.id)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '大纲发布失败'
    } finally {
      loading.value = false
    }
  }

  return {
    biographyId,
    highlightSessionId,
    highlightMessages,
    highlightInput,
    highlightReady,
    outline,
    loading,
    error,
    startHighlight,
    sendHighlight,
    save,
    publish,
  }
}
