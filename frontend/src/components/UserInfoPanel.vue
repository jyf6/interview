<script setup>
defineProps({
  form: {
    type: Object,
    required: true,
  },
  userId: String,
  saving: Boolean,
  savedAt: String,
})

defineEmits(['update-field', 'submit'])
</script>

<template>
  <section class="userinfo-panel">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">User Info</p>
        <h2>用户信息</h2>
      </div>
      <span v-if="savedAt" class="saved-text">已保存 {{ savedAt }}</span>
    </div>

    <form class="userinfo-form" @submit.prevent="$emit('submit')">
      <label>
        <span>姓名</span>
        <input
          :value="form.name"
          type="text"
          placeholder="例如：王阿姨"
          @input="$emit('update-field', 'name', $event.target.value)"
        />
      </label>
      <label>
        <span>性别</span>
        <input
          :value="form.gender"
          type="text"
          placeholder="例如：女 / 男 / 未知"
          @input="$emit('update-field', 'gender', $event.target.value)"
        />
      </label>
      <label>
        <span>年龄</span>
        <input
          :value="form.age"
          type="text"
          placeholder="例如：72"
          @input="$emit('update-field', 'age', $event.target.value)"
        />
      </label>
      <label>
        <span>上次使用时间</span>
        <input
          :value="form.last_used_at"
          type="text"
          placeholder="例如：2026-06-10T18:30:00"
          @input="$emit('update-field', 'last_used_at', $event.target.value)"
        />
      </label>
      <button type="submit" :disabled="!userId.trim() || saving">
        {{ saving ? '保存中...' : '保存用户信息' }}
      </button>
    </form>
  </section>
</template>
