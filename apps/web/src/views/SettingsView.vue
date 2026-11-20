<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type SessionView } from '../api/client'
import { loadSession, session } from '../composables/session'
import { t } from '../i18n'

// 设置页（04 §5.12；P15 精简）：修改密码 / 会话管理。
// 移除「显示偏好」（时区/默认排序）——客户反馈无实际用途。
const loading = ref(true)
const error = ref('')
const notice = ref('')

const oldPassword = ref('')
const newPassword = ref('')
const pwdBusy = ref(false)

const sessions = ref<SessionView[]>([])

onMounted(async () => {
  await loadSession(true)
  try {
    const ss = await api.get<SessionView[]>('/api/v1/settings/sessions')
    sessions.value = ss.data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
})

async function changePassword() {
  if (pwdBusy.value) return
  error.value = ''
  notice.value = ''
  pwdBusy.value = true
  try {
    const { data } = await api.post<{ revoked_sessions: number }>(
      '/api/v1/settings/password',
      { old_password: oldPassword.value, new_password: newPassword.value },
    )
    notice.value =
      t('settings.pwd_ok', {
        suffix: data.revoked_sessions ? t('settings.pwd_ok_revoked', { n: data.revoked_sessions }) : '',
      })
    oldPassword.value = ''
    newPassword.value = ''
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    pwdBusy.value = false
  }
}

async function revokeOthers() {
  error.value = ''
  notice.value = ''
  try {
    const { data } = await api.post<{ revoked: number }>(
      '/api/v1/settings/sessions/revoke-others')
    notice.value = t('settings.revoke_ok', { n: data.revoked })
    sessions.value = (await api.get<SessionView[]>('/api/v1/settings/sessions')).data
  } catch (e) {
    error.value = (e as { message: string }).message
  }
}

function fmt(s?: string): string {
  return s ? new Date(s).toLocaleString() : '—'
}
</script>

<template>
  <section>
    <h1 class="page-title">{{ t('settings.title') }}</h1>
    <p class="page-sub">{{ t('settings.sub') }}</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="notice" class="ok-box" role="status">{{ notice }}</p>
    <p v-if="loading" class="hint" role="status">{{ t('common.loading') }}</p>

    <template v-else>
      <div class="card">
        <h3>{{ t('settings.pwd_title') }}</h3>
        <p class="hint">{{ session.me?.email }}</p>
        <div class="form-row">
          <input v-model="oldPassword" type="password" :placeholder="t('settings.pwd_current')" />
          <input v-model="newPassword" type="password" :placeholder="t('settings.pwd_new')" />
          <button class="btn sm" :disabled="pwdBusy || !oldPassword || newPassword.length < 8"
                  @click="changePassword">
            {{ t('settings.pwd_btn') }}
          </button>
        </div>
        <p class="hint">{{ t('settings.pwd_hint') }}</p>
      </div>

      <div class="card">
        <h3>{{ t('settings.sessions_title') }}</h3>
        <table class="list">
          <thead><tr><th>{{ t('settings.th.login_at') }}</th><th>{{ t('settings.th.expires_at') }}</th><th>{{ t('common.th.status') }}</th></tr></thead>
          <tbody>
            <tr v-for="s in sessions" :key="s.id">
              <td>{{ fmt(s.created_at) }}</td>
              <td>{{ fmt(s.expires_at) }}</td>
              <td>
                <span v-if="s.revoked" class="badge muted">{{ t('settings.session.revoked') }}</span>
                <span v-else-if="s.current" class="badge">{{ t('settings.session.current') }}</span>
                <span v-else class="badge muted">{{ t('settings.session.other') }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <button class="btn sm ghost" @click="revokeOthers">{{ t('settings.revoke_others') }}</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.form-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin: 8px 0; }
.form-row input { max-width: 220px; }
.ok-box { border-left: 4px solid var(--ok, #3a3); padding: 8px 12px; }
.badge.muted { opacity: 0.6; }
</style>
