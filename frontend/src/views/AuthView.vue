<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ArrowLeft, KeyRound, LogIn, Mail, UserPlus } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'

import creatorAuthImage from '../assets/images/creator-auth.jpg'
import PasswordField from '../components/PasswordField.vue'
import { confirmPasswordReset, recoverAccount, requestPasswordReset } from '../api/auth'
import { signIn, signUp } from '../auth'

const route = useRoute()
const router = useRouter()
const form = reactive({
  username: '',
  email: '',
  password: '',
  password1: '',
  password2: '',
  rememberMe: false,
})
const submitting = ref(false)
const errorMessage = ref('')
const fieldErrors = ref({})
const successMessage = ref('')

const mode = computed(() => route.meta.authMode || 'login')
const content = computed(() => ({
  login: {
    eyebrow: 'WELCOME BACK',
    title: '登录造物者',
    description: '输入账号和密码，进入造物者直播间工作台。',
    action: '登录',
  },
  register: {
    eyebrow: 'CREATE ACCOUNT',
    title: '注册账号',
    description: '创建账号后，任务记录会与账号绑定并支持跨电脑查询。',
    action: '注册并进入',
  },
  recoverAccount: {
    eyebrow: 'ACCOUNT RECOVERY',
    title: '找回账号',
    description: '输入注册邮箱，系统会将对应账号发送到邮箱。',
    action: '发送账号信息',
  },
  forgotPassword: {
    eyebrow: 'PASSWORD RESET',
    title: '忘记密码',
    description: '输入注册邮箱，系统会发送限时有效的密码重置链接。',
    action: '发送重置链接',
  },
  resetPassword: {
    eyebrow: 'NEW PASSWORD',
    title: '设置新密码',
    description: '输入两次新密码，完成后使用新密码登录。',
    action: '确认重置密码',
  },
})[mode.value])

const actionIcon = computed(() => ({
  login: LogIn,
  register: UserPlus,
  recoverAccount: Mail,
  forgotPassword: Mail,
  resetPassword: KeyRound,
})[mode.value])

function firstFieldError(name) {
  const messages = fieldErrors.value[name]
  return Array.isArray(messages) ? messages[0] : ''
}

function resetFeedback() {
  errorMessage.value = ''
  fieldErrors.value = {}
  successMessage.value = ''
}

async function submit() {
  resetFeedback()
  submitting.value = true
  try {
    if (mode.value === 'login') {
      await signIn({ username: form.username, password: form.password, remember_me: form.rememberMe })
      const destination = typeof route.query.next === 'string' && route.query.next.startsWith('/')
        ? route.query.next
        : '/'
      await router.replace(destination)
    } else if (mode.value === 'register') {
      await signUp({
        username: form.username,
        email: form.email,
        password1: form.password1,
        password2: form.password2,
      })
      await router.replace('/')
    } else if (mode.value === 'recoverAccount') {
      const response = await recoverAccount({ email: form.email })
      successMessage.value = response.message
    } else if (mode.value === 'forgotPassword') {
      const response = await requestPasswordReset({ email: form.email })
      successMessage.value = response.message
    } else if (mode.value === 'resetPassword') {
      const response = await confirmPasswordReset({
        uid: route.params.uid,
        token: route.params.token,
        password1: form.password1,
        password2: form.password2,
      })
      successMessage.value = response.message
      window.setTimeout(() => router.replace('/login'), 1200)
    }
  } catch (error) {
    errorMessage.value = error.message || '操作失败，请稍后重试。'
    fieldErrors.value = error.payload?.field_errors || {}
  } finally {
    submitting.value = false
  }
}

watch(mode, () => {
  resetFeedback()
  form.password = ''
  form.password1 = ''
  form.password2 = ''
})
</script>

<template>
  <section class="auth-page">
    <div class="auth-brand-panel">
      <img :src="creatorAuthImage" alt="造物者" />
      <div>
        <span>CREATOR LIVE COMMERCE</span>
        <p>认真创造，让每一次被看见都更从容。</p>
      </div>
    </div>

    <div class="auth-form-panel">
      <div class="auth-form-inner">
        <RouterLink v-if="mode !== 'login'" class="auth-back-link" to="/login">
          <ArrowLeft :size="17" aria-hidden="true" />
          返回登录
        </RouterLink>

        <p class="eyebrow">{{ content.eyebrow }}</p>
        <h1>{{ content.title }}</h1>
        <p class="auth-description">{{ content.description }}</p>

        <form class="auth-form" @submit.prevent="submit">
          <label v-if="mode === 'login' || mode === 'register'" class="auth-field">
            <span>账号</span>
            <input
              v-model.trim="form.username"
              type="text"
              autocomplete="username"
              placeholder="请输入账号"
              required
            />
            <small v-if="firstFieldError('username')" class="auth-field-error">
              {{ firstFieldError('username') }}
            </small>
          </label>

          <label v-if="mode === 'register' || mode === 'recoverAccount' || mode === 'forgotPassword'" class="auth-field">
            <span>邮箱</span>
            <input
              v-model.trim="form.email"
              type="email"
              autocomplete="email"
              placeholder="请输入注册邮箱"
              required
            />
            <small v-if="firstFieldError('email')" class="auth-field-error">
              {{ firstFieldError('email') }}
            </small>
          </label>

          <PasswordField
            v-if="mode === 'login'"
            v-model="form.password"
            label="密码"
            autocomplete="current-password"
            :error="firstFieldError('password')"
          />

          <PasswordField
            v-if="mode === 'register' || mode === 'resetPassword'"
            v-model="form.password1"
            :label="mode === 'register' ? '设置密码' : '新密码'"
            autocomplete="new-password"
            placeholder="请输入至少 8 位密码"
            :error="firstFieldError(mode === 'resetPassword' ? 'new_password1' : 'password1')"
          />

          <PasswordField
            v-if="mode === 'register' || mode === 'resetPassword'"
            v-model="form.password2"
            label="确认密码"
            autocomplete="new-password"
            placeholder="请再次输入密码"
            :error="firstFieldError(mode === 'resetPassword' ? 'new_password2' : 'password2')"
          />

          <div v-if="mode === 'login'" class="auth-login-options">
            <label>
              <input v-model="form.rememberMe" type="checkbox" />
              <span>保持登录</span>
            </label>
            <RouterLink to="/forgot-password">忘记密码</RouterLink>
          </div>

          <p v-if="errorMessage" class="auth-message is-error">{{ errorMessage }}</p>
          <p v-if="successMessage" class="auth-message is-success">{{ successMessage }}</p>

          <button class="auth-submit-button" type="submit" :disabled="submitting || Boolean(successMessage)">
            <component :is="actionIcon" :size="18" aria-hidden="true" />
            {{ submitting ? '正在处理...' : content.action }}
          </button>
        </form>

        <div v-if="mode === 'login'" class="auth-secondary-links">
          <span>还没有账号？</span>
          <RouterLink to="/register">立即注册</RouterLink>
          <RouterLink to="/recover-account">忘记账号</RouterLink>
        </div>
      </div>
    </div>
  </section>
</template>
