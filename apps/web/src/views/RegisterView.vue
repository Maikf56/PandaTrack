<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api/client'
import { t } from '../i18n'
import { newRequestId } from '../logic/draft'

// 注册（P16）：开放注册 + 管理员审核后才能登录。
// 成功后停留在本页展示"等待审核"状态，不自动登录（服务端也不发会话）。
const email = ref('')
const password = ref('')
const confirm = ref('')
const inviteCode = ref('')
const error = ref('')
const submitting = ref(false)
const done = ref(false)

async function submit() {
  if (submitting.value) return
  error.value = ''
  const mail = email.value.trim()
  if (!mail.includes('@') || mail.length < 5 || password.value.length < 8) {
    error.value = t('register.err_short')
    return
  }
  if (password.value !== confirm.value) {
    error.value = t('register.err_mismatch')
    return
  }
  submitting.value = true
  try {
    const code = inviteCode.value.trim().toUpperCase()
    await api.post('/api/v1/auth/register', {
      email: mail,
      password: password.value,
      client_request_id: newRequestId(),
      ...(code ? { invite_code: code } : {}),
    })
    done.value = true
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="reg-wrap">
    <div class="card reg-card">
      <template v-if="done">
        <h1 class="page-title">{{ t('register.done_title') }}</h1>
        <div class="ok-box" role="status">{{ t('register.done_body') }}</div>
        <RouterLink class="btn reg-btn" to="/login">{{ t('register.to_login') }}</RouterLink>
      </template>
      <template v-else>
        <h1 class="page-title">{{ t('register.title') }}</h1>
        <p class="page-sub">{{ t('register.sub') }}</p>
        <form @submit.prevent="submit">
          <label for="reg-email">{{ t('register.email') }}</label>
          <input id="reg-email" v-model="email" type="email" autocomplete="email" required />
          <label for="reg-pw">{{ t('register.password') }}</label>
          <input id="reg-pw" v-model="password" type="password" autocomplete="new-password" required minlength="8" />
          <label for="reg-pw2">{{ t('register.confirm') }}</label>
          <input id="reg-pw2" v-model="confirm" type="password" autocomplete="new-password" required minlength="8" />
          <label for="reg-invite">{{ t('register.invite_code') }}</label>
          <input id="reg-invite" v-model="inviteCode" autocomplete="off" maxlength="16"
                 style="text-transform: uppercase" />
          <p class="hint">{{ t('register.invite_hint') }}</p>
          <p v-if="error" class="error-box" role="alert">{{ error }}</p>
          <button class="btn reg-btn" type="submit" :disabled="submitting">
            {{ submitting ? t('register.submitting') : t('register.submit') }}
          </button>
        </form>
        <p class="hint links">
          <RouterLink to="/login">{{ t('register.have_account') }}</RouterLink>
        </p>
      </template>
    </div>
  </section>
</template>

<style scoped>
.reg-wrap { display: flex; justify-content: center; }
.reg-card { width: 100%; max-width: 420px; }
label { display: block; font-weight: 600; margin: 14px 0 6px; }
.reg-btn { width: 100%; margin-top: 22px; }
.links { margin-top: 16px; text-align: center; }
</style>
