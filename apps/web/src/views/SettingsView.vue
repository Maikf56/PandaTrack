<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type SessionView } from '../api/client'
import { loadSession, session } from '../composables/session'

// 设置页（04 §5.12）：修改密码 / 会话管理 / 显示偏好。
const loading = ref(true)
const error = ref('')
const notice = ref('')

const oldPassword = ref('')
const newPassword = ref('')
const pwdBusy = ref(false)

const sessions = ref<SessionView[]>([])
const prefs = ref<{ timezone?: string; default_sort?: string }>({})

const TIMEZONES = ['Asia/Shanghai', 'UTC', 'America/New_York', 'America/Los_Angeles']
const SORTS = [
  { value: 'created_desc', label: '最新提交在前' },
  { value: 'created_asc', label: '最早提交在前' },
  { value: 'status', label: '按状态' },
]

onMounted(async () => {
  await loadSession(true)
  try {
    const [ss, pf] = await Promise.all([
      api.get<SessionView[]>('/api/v1/settings/sessions'),
      api.get<Record<string, string>>('/api/v1/settings/preferences'),
    ])
    sessions.value = ss.data
    prefs.value = pf.data
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
      `密码已修改${data.revoked_sessions ? `，已退出其它 ${data.revoked_sessions} 个会话` : ''}。`
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
    notice.value = `已退出其它 ${data.revoked} 个会话。`
    sessions.value = (await api.get<SessionView[]>('/api/v1/settings/sessions')).data
  } catch (e) {
    error.value = (e as { message: string }).message
  }
}

async function savePrefs() {
  error.value = ''
  notice.value = ''
  try {
    prefs.value = await api.patch<Record<string, string>>(
      '/api/v1/settings/preferences', {
        timezone: prefs.value.timezone || null,
        default_sort: prefs.value.default_sort || null,
      }).then((r) => r.data)
    notice.value = '显示偏好已保存。'
  } catch (e) {
    error.value = (e as { message: string }).message
  }
}

function fmt(t?: string): string {
  return t ? new Date(t).toLocaleString() : '—'
}
</script>

<template>
  <section>
    <h1 class="page-title">设置</h1>
    <p class="page-sub">账户安全与显示偏好。</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="notice" class="ok-box" role="status">{{ notice }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <template v-else>
      <div class="card">
        <h3>修改密码</h3>
        <p class="hint">{{ session.me?.email }}</p>
        <div class="form-row">
          <input v-model="oldPassword" type="password" placeholder="当前密码" />
          <input v-model="newPassword" type="password" placeholder="新密码（至少 8 位）" />
          <button class="btn sm" :disabled="pwdBusy || !oldPassword || newPassword.length < 8"
                  @click="changePassword">
            修改密码
          </button>
        </div>
        <p class="hint">修改成功后会默认退出其它设备的登录会话。</p>
      </div>

      <div class="card">
        <h3>登录会话</h3>
        <table class="list">
          <thead><tr><th>登录时间</th><th>过期时间</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="s in sessions" :key="s.id">
              <td>{{ fmt(s.created_at) }}</td>
              <td>{{ fmt(s.expires_at) }}</td>
              <td>
                <span v-if="s.revoked" class="badge muted">已退出</span>
                <span v-else-if="s.current" class="badge">当前会话</span>
                <span v-else class="badge muted">其它会话</span>
              </td>
            </tr>
          </tbody>
        </table>
        <button class="btn sm ghost" @click="revokeOthers">退出其它会话</button>
      </div>

      <div class="card">
        <h3>显示偏好</h3>
        <div class="form-row">
          <label>时区
            <select v-model="prefs.timezone">
              <option value="">跟随浏览器</option>
              <option v-for="tz in TIMEZONES" :key="tz" :value="tz">{{ tz }}</option>
            </select>
          </label>
          <label>结果列表默认排序
            <select v-model="prefs.default_sort">
              <option value="">默认（最新在前）</option>
              <option v-for="s in SORTS" :key="s.value" :value="s.value">{{ s.label }}</option>
            </select>
          </label>
          <button class="btn sm" @click="savePrefs">保存偏好</button>
        </div>
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
