<script setup>
defineProps({
  active: Boolean,
  activeStep: Object,
  guideTitle: String,
  progress: String,
  highlightStyle: Object,
  popoverStyle: Object,
})

defineEmits(['close', 'next'])
</script>

<template>
  <div v-if="active && activeStep" class="onboarding-layer" aria-live="polite">
    <button class="onboarding-backdrop" type="button" aria-label="关闭引导" @click="$emit('close')"></button>
    <div class="onboarding-highlight" :style="highlightStyle"></div>
    <section class="onboarding-popover" :style="popoverStyle">
      <div class="onboarding-meta">
        <span>{{ guideTitle }}</span>
        <span>{{ progress }}</span>
      </div>
      <h2>{{ activeStep.title }}</h2>
      <p>{{ activeStep.body }}</p>
      <div class="onboarding-actions">
        <button
          type="button"
          class="text-button"
          data-onboarding-target="guide_skip_button"
          @click="$emit('close')"
        >
          跳过
        </button>
        <button type="button" class="primary-button" @click="$emit('next')">
          {{ activeStep.primary_action_label }}
        </button>
      </div>
    </section>
  </div>
</template>
