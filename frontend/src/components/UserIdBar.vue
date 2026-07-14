<script setup>
defineProps({
  modelValue: String,
  loading: Boolean,
})

defineEmits(['update:modelValue', 'start'])
</script>

<template>
  <section class="user-id-bar">
    <label>
      <span>用户 ID</span>
      <input
        :value="modelValue"
        type="text"
        placeholder="请输入用户唯一 ID"
        :disabled="loading"
        @input="$emit('update:modelValue', $event.target.value)"
      />
    </label>
    <button type="button" :disabled="loading || !modelValue.trim()" @click="$emit('start')">
      使用该用户开始
    </button>
  </section>
</template>
