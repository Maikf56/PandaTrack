<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import { loadSession, session } from '../composables/session'
import { t } from '../i18n'
import { newRequestId } from '../logic/draft'

// 登录（04 §5.2）：只留邮箱/密码/登录/忘记密码/试用入口；失败显示白话错误。
const route = useRoute()
const router = useRouter()

const email = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

onMounted(async () => {
  // 已登录用户直接回目标页
  const me = await loadSession(true)
  if (me) goNext()
})

const DRAFT_STORAGE_KEY = 'pt_home_draft'

function goNext() {
  const next = typeof route.query.next === 'string' ? route.query.next : '/dashboard'
  router.push(next)
}

async function submit() {
  if (submitting.value) return
  error.value = ''
  if (!email.value || password.value.length < 8) {
    error.value = t('login.err_short')
    return
  }
  submitting.value = true
  try {
    await api.post('/api/v1/auth/login', {
      email: email.value.trim(),
      password: password.value,
      client_request_id: newRequestId(),
    })
    session.me = await loadSession(true)
    // 恢复首页草稿到 /quick（04 验收用例 1）
    const draft = sessionStorage.getItem(DRAFT_STORAGE_KEY)
    if (draft && route.query.next === '/quick') {
      sessionStorage.setItem('pt_quick_draft_text', draft)
      sessionStorage.removeItem(DRAFT_STORAGE_KEY)
    }
    goNext()
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="login-wrap">
    <div class="card login-card">
      <h1 class="page-title">{{ t('login.title') }}</h1>
      <p class="page-sub">{{ t('login.sub') }}</p>
      <form @submit.prevent="submit">
        <label for="login-email">{{ t('login.email') }}</label>
        <input id="login-email" v-model="email" type="email" autocomplete="email" required />
        <label for="login-pw">{{ t('login.password') }}</label>
        <input id="login-pw" v-model="password" type="password" autocomplete="current-password" required />
        <p v-if="error" class="error-box" role="alert">{{ error }}</p>
        <button class="btn login-btn" type="submit" :disabled="submitting">
          {{ submitting ? t('login.submitting') : t('login.title') }}
        </button>
      </form>
      <p class="hint links">
        <RouterLink to="/forgot">{{ t('login.forgot') }}</RouterLink>
        ·
        <RouterLink to="/register">{{ t('login.to_register') }}</RouterLink>
        ·
        <RouterLink to="/trial">{{ t('nav.trial') }}</RouterLink>
      </p>
    </div>
  </section>
</template>

<style scoped>
.login-wrap { display: flex; justify-content: center; }
.login-card { width: 100%; max-width: 420px; }
label { display: block; font-weight: 600; margin: 14px 0 6px; }
/* 登录按钮与输入框拉开间距：全宽 + 上边距，链接组独立成行（P16 反馈） */
.login-btn { width: 100%; margin-top: 22px; }
.links { margin-top: 16px; text-align: center; }
</style>
