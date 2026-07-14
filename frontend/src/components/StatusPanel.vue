<script setup>
defineProps({
  statePolling: Boolean,
  stateText: String,
  stateLabel: String,
  sessionId: String,
  userId: String,
  stageText: String,
  stageTitle: String,
  stageDescription: String,
  completedText: String,
  progressText: String,
  stateSteps: {
    type: Array,
    default: () => [],
  },
  currentStateIndex: Number,
})
</script>

<template>
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
        <span class="stage-code">{{ stageText }}</span>
        <strong>{{ stageTitle }}</strong>
      </div>
      <p>{{ stageDescription }}</p>
      <small>{{ completedText }} · {{ progressText }}</small>
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
</template>
