import { computed, nextTick, ref } from 'vue'
import { ONBOARDING_GUIDE } from '../constants/interviewUi'

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max)
}

export function useOnboarding() {
  const guide = ref(null)
  const active = ref(false)
  const index = ref(0)
  const targetRect = ref(null)

  const activeStep = computed(() => guide.value?.steps?.[index.value] ?? null)
  const progress = computed(() => {
    const total = guide.value?.steps?.length ?? 0
    return total ? `${index.value + 1}/${total}` : ''
  })
  const guideTitle = computed(() => guide.value?.title ?? '')
  const highlightStyle = computed(() => {
    if (!active.value || !targetRect.value) return { display: 'none' }
    return {
      top: `${targetRect.value.top - 6}px`,
      left: `${targetRect.value.left - 6}px`,
      width: `${targetRect.value.width + 12}px`,
      height: `${targetRect.value.height + 12}px`,
    }
  })
  const popoverStyle = computed(() => {
    if (!active.value || !activeStep.value || !targetRect.value) {
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

  function getTargetElement(targetKey) {
    if (!targetKey) return null
    return document.querySelector(`[data-onboarding-target="${targetKey}"]`)
  }

  function refreshTarget() {
    nextTick(() => {
      if (!active.value || !activeStep.value) return
      const element = getTargetElement(activeStep.value.target_key)
      targetRect.value = element ? element.getBoundingClientRect() : null
    })
  }

  function start() {
    guide.value = {
      ...ONBOARDING_GUIDE,
      steps: [...ONBOARDING_GUIDE.steps].sort((a, b) => a.sequence - b.sequence),
    }
    active.value = true
    index.value = 0
    refreshTarget()
  }

  function next() {
    const total = guide.value?.steps?.length ?? 0
    if (index.value + 1 >= total) {
      close()
      return
    }
    index.value += 1
    refreshTarget()
  }

  function close() {
    active.value = false
    targetRect.value = null
  }

  return {
    active,
    activeStep,
    guideTitle,
    progress,
    highlightStyle,
    popoverStyle,
    start,
    next,
    close,
    refreshTarget,
  }
}
