<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, adminSession, type AdminMe } from '../api/client'

// 管理端登录（03 §3.1）：独立会话 Cookie（path=/api/v1/admin），短时效。
const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const submitting = ref(false)
const error = ref('')

async function login() {
  if (!username.value || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const me = await api.post<AdminMe>('/api/v1/admin/auth/login', {
      username: username.value,
      password: password.value,
    })
    adminSession.me = me
    const next = typeof route.query.next === 'string' ? route.query.next : '/'
    router.push(next)
  } catch (e) {
    error.value = (e as { message: string }).message || '登录失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-card card">
    <h1 class="page-title">PandaTrack 管理端</h1>
    <p class="page-sub">仅限内部运营与运维人员；操作全程审计。</p>
    <form @submit.prevent="login">
      <label for="adm-user" class="field-label">用户名</label>
      <input id="adm-user" v-model="username" autocomplete="username" />
      <label for="adm-pass" class="field-label" style="margin-top: 12px">密码</label>
      <input id="adm-pass" v-model="password" type="password" autocomplete="current-password" />
      <p v-if="error" class="error-box" role="alert">{{ error }}</p>
      <button class="btn" type="submit" :disabled="submitting" style="margin-top: 16px; width: 100%">
        {{ submitting ? '登录中…' : '登录' }}
      </button>
    </form>
    <p class="hint" style="margin-top: 12px">
      登录即表示同意：所有操作（客户状态、账务调整、Provider 启停）将记录操作者、对象与理由。
    </p>
  </div>
</template>

<style scoped>
.login-card { width: min(400px, 92vw); box-shadow: var(--shadow-1); }
</style>
