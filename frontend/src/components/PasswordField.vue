<script setup>
import { Eye, EyeOff } from '@lucide/vue'
import { ref } from 'vue'

defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, required: true },
  autocomplete: { type: String, default: 'current-password' },
  placeholder: { type: String, default: '请输入密码' },
  error: { type: String, default: '' },
})

defineEmits(['update:modelValue'])

const visible = ref(false)
</script>

<template>
  <label class="auth-field">
    <span>{{ label }}</span>
    <div class="password-input-wrap">
      <input
        :value="modelValue"
        :type="visible ? 'text' : 'password'"
        :autocomplete="autocomplete"
        :placeholder="placeholder"
        @input="$emit('update:modelValue', $event.target.value)"
      />
      <button
        type="button"
        :aria-label="visible ? '隐藏密码' : '显示密码'"
        :title="visible ? '隐藏密码' : '显示密码'"
        @click="visible = !visible"
      >
        <EyeOff v-if="visible" :size="19" aria-hidden="true" />
        <Eye v-else :size="19" aria-hidden="true" />
      </button>
    </div>
    <small v-if="error" class="auth-field-error">{{ error }}</small>
  </label>
</template>
