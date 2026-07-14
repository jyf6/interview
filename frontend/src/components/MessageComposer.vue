<script setup>
import { SendHorizontal } from 'lucide-vue-next'

defineProps({
  modelValue: String,
  canType: Boolean,
  loading: Boolean,
})

defineEmits(['update:modelValue', 'send'])
</script>

<template>
  <form class="composer" data-onboarding-target="composer" @submit.prevent="$emit('send')">
    <input
      :value="modelValue"
      type="text"
      :disabled="!canType || loading"
      :placeholder="canType ? '输入你的回答...' : '请先通过卡片完成采访前引导'"
      @input="$emit('update:modelValue', $event.target.value)"
    />
    <button type="submit" :disabled="!canType || loading || !modelValue.trim()" title="发送">
      <SendHorizontal :size="18" aria-hidden="true" />
      <span>发送</span>
    </button>
  </form>
</template>
