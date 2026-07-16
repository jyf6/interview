<script setup>
import { CheckCircle2 } from 'lucide-vue-next'

defineEmits(['complete-point'])
defineProps({
  stageText: String,
  title: String,
  description: String,
  statusText: String,
  progressText: String,
  stateLabel: String,
  responseSource: String,
  activePoint: {
    type: Object,
    default: null,
  },
  canCompletePoint: Boolean,
})
</script>

<template>
  <section class="interview-stage-banner" aria-label="当前采访状态">
    <div class="stage-main">
      <span class="stage-code">{{ stageText }}</span>
      <div>
        <p class="eyebrow">当前采访状态</p>
        <h2>{{ title }}</h2>
      </div>
    </div>
    <p>{{ description }}</p>
    <div v-if="activePoint?.title" class="collection-point">
      <div>
        <span class="eyebrow">当前采集点</span>
        <strong>{{ activePoint.title }}</strong>
        <p v-if="activePoint.hook">{{ activePoint.hook }}</p>
      </div>
      <button type="button" class="point-complete-button" :disabled="!canCompletePoint" @click="$emit('complete-point')">
        <CheckCircle2 :size="16" aria-hidden="true" />
        <span>完成本段</span>
      </button>
    </div>
    <div class="stage-meta">
      <span>{{ statusText }}</span>
      <span>{{ progressText }}</span>
      <span>流程状态：{{ stateLabel }}</span>
      <span>来源：{{ responseSource }}</span>
    </div>
  </section>
</template>
