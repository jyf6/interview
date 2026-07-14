<script setup>
defineProps({
  stageText: String,
  title: String,
  description: String,
  statusText: String,
  progressText: String,
  stateLabel: String,
  responseSource: String,
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
    <div class="stage-meta">
      <span>{{ statusText }}</span>
      <span>{{ progressText }}</span>
      <span>流程状态：{{ stateLabel }}</span>
      <span>来源：{{ responseSource }}</span>
    </div>
  </section>
</template>
