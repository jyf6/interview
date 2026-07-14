<script setup>
import { ref } from 'vue'
import { MESSAGE_ROLE_LABELS } from '../constants/interviewUi'

defineProps({
  messages: {
    type: Array,
    default: () => [],
  },
  loading: Boolean,
  streamingOpening: String,
})

const transcript = ref(null)

function scrollToBottom() {
  if (transcript.value) {
    transcript.value.scrollTop = transcript.value.scrollHeight
  }
}

defineExpose({ scrollToBottom })
</script>

<template>
  <section ref="transcript" class="chat-area">
    <article v-for="message in messages" :key="message.id" class="message-row" :class="message.role">
      <div class="avatar">
        {{ MESSAGE_ROLE_LABELS[message.role] ?? '记' }}
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
</template>
