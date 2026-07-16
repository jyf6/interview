<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { FileText, Info, MessageCircle } from 'lucide-vue-next'
import AppHeader from './components/AppHeader.vue'
import CardOptions from './components/CardOptions.vue'
import ChatTranscript from './components/ChatTranscript.vue'
import InterviewStageBanner from './components/InterviewStageBanner.vue'
import MessageComposer from './components/MessageComposer.vue'
import OnboardingGuide from './components/OnboardingGuide.vue'
import OutlineConsole from './components/OutlineConsole.vue'
import StatusPanel from './components/StatusPanel.vue'
import UserIdBar from './components/UserIdBar.vue'
import UserInfoPanel from './components/UserInfoPanel.vue'
import { useInterviewDialog } from './composables/useInterviewDialog'
import { useOnboarding } from './composables/useOnboarding'
import { useOutlineConsole } from './composables/useOutlineConsole'
import { STATE_STEPS } from './constants/interviewUi'

const dialog = useInterviewDialog()
const outline = useOutlineConsole(dialog.userId)
const onboarding = useOnboarding()
const transcriptRef = ref(null)
const activePage = ref('outline')
const pageTitle = computed(() => (activePage.value === 'chat' ? '传记采访引导' : activePage.value === 'outline' ? '传记大纲' : '采访信息'))

async function startOutlineInterview() {
  await dialog.startPublishedOutline(outline.biographyId.value, outline.outline.value?.id)
  activePage.value = 'chat'
}

function scrollTranscript() {
  nextTick(() => {
    transcriptRef.value?.scrollToBottom?.()
  })
}

watch(
  () => [dialog.messages.value.length, dialog.streamingOpening.value],
  () => scrollTranscript(),
)

</script>

<template>
  <main class="app-shell">
    <div class="page-frame">
      <nav class="page-tabs" aria-label="页面切换">
        <button
          type="button"
          :class="{ active: activePage === 'chat' }"
          :aria-current="activePage === 'chat' ? 'page' : undefined"
          @click="activePage = 'chat'"
        >
          <MessageCircle :size="18" aria-hidden="true" />
          <span>聊天</span>
        </button>
        <button
          type="button"
          :class="{ active: activePage === 'outline' }"
          :aria-current="activePage === 'outline' ? 'page' : undefined"
          @click="activePage = 'outline'"
        >
          <FileText :size="18" aria-hidden="true" />
          <span>大纲</span>
        </button>
        <button
          type="button"
          v-if="false"
          :class="{ active: activePage === 'info' }"
          :aria-current="activePage === 'info' ? 'page' : undefined"
          @click="activePage = 'info'"
        >
          <Info :size="18" aria-hidden="true" />
          <span>信息</span>
        </button>
      </nav>

      <section v-if="activePage === 'chat'" class="chat-panel chat-page" data-onboarding-target="chat_panel">
        <AppHeader
          :title="pageTitle"
          :loading="dialog.loading.value"
          :session-id="dialog.sessionId.value"
          :current-state="dialog.currentState.value"
          :show-actions="false"
        />

        <div v-if="dialog.error.value" class="error-box">
          {{ dialog.error.value }}
        </div>

        <ChatTranscript
          ref="transcriptRef"
          :messages="dialog.messages.value"
          :loading="dialog.loading.value"
          :streaming-opening="dialog.streamingOpening.value"
        />

        <CardOptions
          :title="dialog.cardsTitle.value"
          :cards="dialog.cards.value"
          :card-group="dialog.cardGroup.value"
          :loading="dialog.loading.value"
          :custom-question-open="dialog.customQuestionOpen.value"
          :custom-question="dialog.customQuestion.value"
          @choose-card="dialog.chooseCard"
          @update:custom-question="dialog.customQuestion.value = $event"
          @send-custom-question="dialog.sendCustomQuestion"
        />

        <MessageComposer
          :model-value="dialog.inputText.value"
          :can-type="dialog.canType.value"
          :loading="dialog.loading.value"
          @update:model-value="dialog.inputText.value = $event"
          @send="dialog.sendText"
        />
      </section>

      <section v-else-if="activePage === 'outline'" class="outline-page">
        <OutlineConsole
          :outline="outline.outline.value"
          :highlight-messages="outline.highlightMessages.value"
          :highlight-input="outline.highlightInput.value"
          :highlight-ready="outline.highlightReady.value"
          :loading="outline.loading.value"
          :error="outline.error.value"
          @update:highlight-input="outline.highlightInput.value = $event"
          @start-highlight="outline.startHighlight"
          @send-highlight="outline.sendHighlight"
          @save="outline.save"
          @publish="outline.publish"
          @start-session="startOutlineInterview"
        />
      </section>

      <section v-else class="info-page">
        <header class="info-header">
          <div>
            <p class="eyebrow">Interview Console</p>
            <h1>采访信息</h1>
          </div>
          <button class="tool-button" type="button" @click="activePage = 'chat'">
            <MessageCircle :size="17" aria-hidden="true" />
            <span>返回聊天</span>
          </button>
        </header>

        <InterviewStageBanner
          :stage-text="dialog.interviewStageText.value"
          :title="dialog.interviewStageTitle.value"
          :description="dialog.interviewStageDescription.value"
          :status-text="dialog.interviewStageStatusText.value"
          :progress-text="dialog.interviewStageProgressText.value"
          :state-label="dialog.stateLabel.value"
          :response-source="dialog.responseSource.value"
          :active-point="dialog.activeCollectionPoint.value"
          :can-complete-point="dialog.canCompleteCollectionPoint.value"
          @complete-point="dialog.completeCollectionPoint"
        />

        <div v-if="dialog.error.value" class="error-box info-error">
          {{ dialog.error.value }}
        </div>

        <UserIdBar
          :model-value="dialog.userId.value"
          :loading="dialog.loading.value"
          @update:model-value="dialog.userId.value = $event"
          @start="dialog.resetDialog"
        />

        <div class="info-grid">
          <StatusPanel
            :state-polling="dialog.statePolling.value"
            :state-text="dialog.stateText.value"
            :state-label="dialog.stateLabel.value"
            :session-id="dialog.sessionId.value"
            :user-id="dialog.userId.value"
            :stage-text="dialog.interviewStageText.value"
            :stage-title="dialog.interviewStageTitle.value"
            :stage-description="dialog.interviewStageDescription.value"
            :completed-text="dialog.interviewCompletedText.value"
            :progress-text="dialog.interviewStageProgressText.value"
            :state-steps="STATE_STEPS"
            :current-state-index="dialog.currentStateIndex.value"
            :active-point="dialog.activeCollectionPoint.value"
          />

          <UserInfoPanel
            :form="dialog.userInfoForm.value"
            :user-id="dialog.userId.value"
            :saving="dialog.userInfoSaving.value"
            :saved-at="dialog.userInfoSavedAt.value"
            @update-field="dialog.updateUserInfoField"
            @submit="dialog.submitUserInfo"
          />
        </div>
      </section>
    </div>

    <OnboardingGuide
      :active="onboarding.active.value"
      :active-step="onboarding.activeStep.value"
      :guide-title="onboarding.guideTitle.value"
      :progress="onboarding.progress.value"
      :highlight-style="onboarding.highlightStyle.value"
      :popover-style="onboarding.popoverStyle.value"
      @close="onboarding.close"
      @next="onboarding.next"
    />
  </main>
</template>
