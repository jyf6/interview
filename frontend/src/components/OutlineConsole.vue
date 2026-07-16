<script setup>
import { FilePlus2, Play, Save, Send } from 'lucide-vue-next'

defineProps({
  outline: { type: Object, default: null },
  highlightMessages: { type: Array, default: () => [] },
  highlightInput: { type: String, default: '' },
  highlightReady: Boolean,
  loading: Boolean,
  error: { type: String, default: '' },
})

defineEmits([
  'update:highlight-input',
  'start-highlight',
  'send-highlight',
  'save',
  'publish',
  'start-session',
])
</script>

<template>
  <section class="outline-console">
    <header class="outline-header">
      <div>
        <p class="eyebrow">Biography Workspace</p>
        <h1>传记采访</h1>
      </div>
      <span v-if="outline" class="outline-status">{{ outline.status }}</span>
    </header>

    <div v-if="!highlightReady" class="highlight-chat">
      <div class="highlight-chat-header">
        <div>
          <h2>先聊一段高光经历</h2>
          <p>通过几轮文字对话，帮您把故事讲完整，再生成专属大纲。</p>
        </div>
        <button v-if="!highlightMessages.length" type="button" class="primary-button" :disabled="loading" @click="$emit('start-highlight')">
          <Play :size="16" aria-hidden="true" />
          <span>开始聊天</span>
        </button>
      </div>

      <div v-if="highlightMessages.length" class="highlight-messages" aria-live="polite">
        <p v-for="(message, index) in highlightMessages" :key="`${index}-${message.role}`" :class="['highlight-message', message.role]">
          {{ message.content }}
        </p>
      </div>

      <form v-if="highlightMessages.length" class="highlight-composer" @submit.prevent="$emit('send-highlight')">
        <textarea
          :value="highlightInput"
          :disabled="loading"
          rows="3"
          placeholder="请输入您想补充的内容"
          @input="$emit('update:highlight-input', $event.target.value)"
        ></textarea>
        <button type="submit" class="primary-button" :disabled="loading || !highlightInput.trim()">
          <Send :size="16" aria-hidden="true" />
          <span>发送</span>
        </button>
      </form>
    </div>

    <p v-if="error" class="outline-error">{{ error }}</p>

    <div v-if="outline" class="outline-tree">
      <article v-for="(chapter, chapterIndex) in outline.chapters" :key="chapterIndex" class="outline-chapter">
        <label>
          章节名称
          <input v-model="chapter.title" :disabled="loading || outline.status !== 'draft'" />
        </label>
        <div v-for="(point, pointIndex) in chapter.points" :key="point.id || pointIndex" class="outline-point">
          <label>
            采集点
            <input v-model="point.title" :disabled="loading || outline.status !== 'draft'" />
          </label>
          <label>
            引入问题
            <textarea v-model="point.hook" :disabled="loading || outline.status !== 'draft'" rows="2"></textarea>
          </label>
        </div>
      </article>
    </div>

    <div v-if="outline" class="outline-actions">
      <button type="button" class="tool-button" :disabled="loading || outline.status !== 'draft'" @click="$emit('save')">
        <Save :size="16" aria-hidden="true" />
        <span>保存草稿</span>
      </button>
      <button type="button" class="primary-button" :disabled="loading || outline.status !== 'draft'" @click="$emit('publish')">
        <Send :size="16" aria-hidden="true" />
        <span>发布大纲</span>
      </button>
      <button type="button" class="primary-button" :disabled="loading || outline.status !== 'published'" @click="$emit('start-session')">
        <FilePlus2 :size="16" aria-hidden="true" />
        <span>开始采集点采访</span>
      </button>
    </div>
  </section>
</template>
