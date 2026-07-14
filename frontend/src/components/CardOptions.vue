<script setup>
defineProps({
  title: String,
  cards: {
    type: Array,
    default: () => [],
  },
  cardGroup: String,
  loading: Boolean,
  customQuestionOpen: Boolean,
  customQuestion: String,
})

defineEmits(['choose-card', 'update:customQuestion', 'send-custom-question'])
</script>

<template>
  <section v-if="cards.length" class="cards-section" data-onboarding-target="card_options">
    <h2>{{ title }}</h2>
    <div class="cards-grid" :class="cardGroup">
      <button
        v-for="card in cards"
        :key="card.card_id"
        class="card-button"
        type="button"
        :disabled="loading"
        @click="$emit('choose-card', card)"
      >
        {{ card.label }}
      </button>
    </div>
    <form v-if="customQuestionOpen" class="custom-question" @submit.prevent="$emit('send-custom-question')">
      <input
        :value="customQuestion"
        type="text"
        placeholder="请输入你想问的问题"
        @input="$emit('update:customQuestion', $event.target.value)"
      />
      <button type="submit" :disabled="!customQuestion.trim() || loading">提问</button>
    </form>
  </section>
</template>
