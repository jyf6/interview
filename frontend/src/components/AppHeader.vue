<script setup>
import { RotateCcw, Undo2 } from 'lucide-vue-next'

defineProps({
  title: {
    type: String,
    default: '传记采访引导',
  },
  loading: Boolean,
  sessionId: String,
  currentState: String,
  showActions: {
    type: Boolean,
    default: true,
  },
})

defineEmits(['reset', 'resume'])
</script>

<template>
  <header class="chat-header">
    <div>
      <p class="eyebrow">Interview Guidance</p>
      <h1>{{ title }}</h1>
    </div>
    <div v-if="showActions" class="header-actions">
      <button
        class="tool-button"
        type="button"
        :disabled="loading || !sessionId || currentState !== 'INTERVIEWING'"
        title="模拟用户退出后再次回来"
        @click="$emit('resume')"
      >
        <Undo2 :size="17" aria-hidden="true" />
        <span>模拟重进</span>
      </button>
      <button
        class="tool-button"
        type="button"
        :disabled="loading"
        title="重新开始"
        data-onboarding-target="reset_button"
        @click="$emit('reset')"
      >
        <RotateCcw :size="17" aria-hidden="true" />
        <span>重新开始</span>
      </button>
    </div>
  </header>
</template>
