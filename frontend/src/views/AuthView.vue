<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ArrowLeft, KeyRound, LogIn, Mail, Send, UserPlus } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'

import creatorAuthImage from '../assets/images/creator-auth.jpg'
import PasswordField from '../components/PasswordField.vue'
import { confirmPasswordReset, recoverAccount, sendVerificationCode } from '../api/auth'
import { signIn, signUp } from '../auth'

const route = useRoute()
const router = useRouter()
const form = reactive({
  username: '',
  email: '',
  code: '',
  password: '',
  password1: '',
  password2: '',
  rememberMe: false,
})
const submitting = ref(false)
const sendingCode = ref(false)
const countdown = ref(0)
const errorMessage = ref('')
const fieldErrors = ref({})
const successMessage = ref('')
const operationComplete = ref(false)
let countdownTimer = null

const mode = computed(() => route.meta.authMode || 'login')
const content = computed(() => ({
  login: {
    eyebrow: 'WELCOME BACK',
    title: '登录知识中心',
    description: '使用用户名和密码登录。',
    action: '登录',
  },
  register: {
    eyebrow: 'CREATE ACCOUNT',
    title: '注册账号',
    description: '填写用户名和邮箱，创建你的造物者账号。',
    action: '注册并进入',
  },
  recoverAccount: {
    eyebrow: 'ACCOUNT RECOVERY',
    title: '找回用户名',
    description: '通过注册邮箱接收验证码，验证后查看用户名。',
    action: '验证并找回用户名',
  },
  forgotPassword: {
    eyebrow: 'PASSWORD RESET',
    title: '忘记密码',
    description: '通过注册邮箱接收验证码，并设置新密码。',
    action: '验证并重置密码',
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
  forgotPassword: KeyRound,
  resetPassword: KeyRound,
})[mode.value])

const needsVerificationCode = computed(() => (
  mode.value === 'recoverAccount'
  || mode.value === 'forgotPassword'
))

function firstFieldError(name) {
  const messages = fieldErrors.value[name]
  return Array.isArray(messages) ? messages[0] : ''
}

function resetFeedback() {
  errorMessage.value = ''
  fieldErrors.value = {}
  successMessage.value = ''
  operationComplete.value = false
}

function stopCountdown() {
  if (countdownTimer) window.clearInterval(countdownTimer)
  countdownTimer = null
  countdown.value = 0
}

function startCountdown(seconds = 60) {
  stopCountdown()
  countdown.value = Math.max(1, Number(seconds) || 60)
  countdownTimer = window.setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) stopCountdown()
  }, 1000)
}

function codeRequest() {
  return {
    channel: 'email',
    purpose: mode.value === 'recoverAccount' ? 'account_recovery' : 'password_reset',
    destination: form.email,
  }
}

async function sendCode() {
  errorMessage.value = ''
  successMessage.value = ''
  sendingCode.value = true
  try {
    const response = await sendVerificationCode(codeRequest())
    if (response.debug_code) form.code = response.debug_code
    successMessage.value = response.debug_code
      ? `${response.message} 本地验证码：${response.debug_code}`
      : response.message
    startCountdown(response.retry_after)
  } catch (error) {
    errorMessage.value = error.message || '验证码发送失败，请稍后重试。'
    if (error.payload?.retry_after) startCountdown(error.payload.retry_after)
  } finally {
    sendingCode.value = false
  }
}

async function submit() {
  resetFeedback()
  submitting.value = true
  try {
    if (mode.value === 'login') {
      const payload = {
        method: 'password',
        username: form.username,
        password: form.password,
        remember_me: form.rememberMe,
      }
      await signIn(payload)
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
      const response = await recoverAccount({ email: form.email, code: form.code })
      successMessage.value = response.message
      operationComplete.value = true
    } else if (mode.value === 'forgotPassword') {
      const response = await confirmPasswordReset({
        email: form.email,
        code: form.code,
        password1: form.password1,
        password2: form.password2,
      })
      successMessage.value = response.message
      operationComplete.value = true
      window.setTimeout(() => router.replace('/login'), 1200)
    } else if (mode.value === 'resetPassword') {
      const response = await confirmPasswordReset({
        uid: route.params.uid,
        token: route.params.token,
        password1: form.password1,
        password2: form.password2,
      })
      successMessage.value = response.message
      operationComplete.value = true
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
  stopCountdown()
  form.code = ''
  form.password = ''
  form.password1 = ''
  form.password2 = ''
})

onBeforeUnmount(stopCountdown)
</script>

<template>
  <section class="auth-page">
    <div class="auth-brand-panel">
      <img :src="creatorAuthImage" alt="造物者" />
      <div>
        <span>造物者直播间知识中心</span>
        <p>让直播经验成为随时可以找到的答案。</p>
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
          <label v-if="mode === 'register' || mode === 'login'" class="auth-field">
            <span>用户名</span>
            <input
              v-model.trim="form.username"
              type="text"
              autocomplete="username"
              placeholder="请输入用户名"
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

          <div v-if="needsVerificationCode" class="auth-field">
            <span>验证码</span>
            <div class="auth-code-row">
              <input
                v-model.trim="form.code"
                type="text"
                inputmode="numeric"
                autocomplete="one-time-code"
                maxlength="6"
                placeholder="请输入 6 位验证码"
                required
              />
              <button type="button" :disabled="sendingCode || countdown > 0" @click="sendCode">
                <Send v-if="countdown === 0" :size="16" aria-hidden="true" />
                {{ countdown > 0 ? `${countdown} 秒` : (sendingCode ? '发送中' : '获取验证码') }}
              </button>
            </div>
          </div>

          <PasswordField
            v-if="mode === 'login'"
            v-model="form.password"
            label="密码"
            autocomplete="current-password"
            :error="firstFieldError('password')"
          />

          <PasswordField
            v-if="mode === 'register' || mode === 'forgotPassword' || mode === 'resetPassword'"
            v-model="form.password1"
            :label="mode === 'register' ? '密码' : '新密码'"
            autocomplete="new-password"
            placeholder="请输入至少 8 位密码"
            :error="firstFieldError(mode === 'register' ? 'password1' : 'new_password1')"
          />

          <PasswordField
            v-if="mode === 'register' || mode === 'forgotPassword' || mode === 'resetPassword'"
            v-model="form.password2"
            label="确认密码"
            autocomplete="new-password"
            placeholder="请再次输入密码"
            :error="firstFieldError(mode === 'register' ? 'password2' : 'new_password2')"
          />

          <div v-if="mode === 'login'" class="auth-login-options">
            <label>
              <input v-model="form.rememberMe" type="checkbox" />
              <span>保持登录</span>
            </label>
            <div class="auth-recovery-links">
              <RouterLink to="/recover-account">忘记用户名</RouterLink>
              <RouterLink to="/forgot-password">忘记密码</RouterLink>
            </div>
          </div>

          <p v-if="errorMessage" class="auth-message is-error">{{ errorMessage }}</p>
          <p v-if="successMessage" class="auth-message is-success">{{ successMessage }}</p>

          <button class="auth-submit-button" type="submit" :disabled="submitting || operationComplete">
            <component :is="actionIcon" :size="18" aria-hidden="true" />
            {{ submitting ? '正在处理...' : content.action }}
          </button>
        </form>

        <div v-if="mode === 'login'" class="auth-secondary-links">
          <span>还没有账号？</span>
          <RouterLink to="/register">立即注册</RouterLink>
        </div>
      </div>
    </div>
  </section>
</template>
