<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, type InviteSummary, type InviteFriendView } from '../api/client'
import { loadSession } from '../composables/session'

// 邀请好友（P15 脚手架）：邀请码/链接/统计/好友列表。
// 奖励结算依赖开放注册——当前无公开注册入口，统计恒为 0，文案如实说明。
const loading = ref(true)
const error = ref('')
const notice = ref('')
const summary = ref<InviteSummary | null>(null)
const friends = ref<InviteFriendView[]>([])
const busy = ref(false)

const link = computed(() =>
  summary.value ? `${window.location.origin}/login?ref=${summary.value.code}` : '')

onMounted(async () => {
  await loadSession(true)
  await reload()
})

async function reload() {
  loading.value = summary.value === null
  error.value = ''
  try {
    const [s, f] = await Promise.all([
      api.get<InviteSummary>('/api/v1/invites/me'),
      api.get<InviteFriendView[]>('/api/v1/invites/friends'),
    ])
    summary.value = s.data
    friends.value = f.data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

async function regenerate() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    summary.value = (await api.post<InviteSummary>('/api/v1/invites/regenerate')).data
    notice.value = '已生成新的邀请码，旧邀请码立即失效。'
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    busy.value = false
  }
}

async function copy(text: string) {
  await navigator.clipboard?.writeText(text)
  notice.value = '已复制到剪贴板。'
}

function fmt(t?: string): string {
  return t ? new Date(t).toLocaleString() : '—'
}
</script>

<template>
  <section>
    <h1 class="page-title">邀请好友</h1>
    <p class="page-sub">分享邀请码或链接，好友注册后你将获得积分奖励。</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="notice" class="ok-box" role="status">{{ notice }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <template v-else-if="summary">
      <div class="card">
        <h3>我的邀请码</h3>
        <p class="hint rule">
          计划规则（注册开放后自动生效）：好友注册并领取体验积分后，你获得
          <strong>1000 积分</strong>一次性奖励；好友每次充值可按充值金额的
          <strong>10%</strong> 获得积分返利（赠送积分不计入）。
        </p>
        <p class="hint warn-note">
          ⓘ 奖励结算依赖「开放注册」——当前账号由管理员开通，以下统计暂时为 0。
        </p>
        <div class="code-row">
          <div class="field">
            <span class="hint">邀请码</span>
            <input :value="summary.code" readonly class="mono" />
          </div>
          <div class="field grow">
            <span class="hint">邀请链接</span>
            <input :value="link" readonly class="mono" />
          </div>
          <div class="btn-col">
            <button class="btn sm" @click="copy(summary.code)">复制码</button>
            <button class="btn sm ghost" @click="copy(link)">复制链接</button>
          </div>
        </div>
        <button class="btn ghost sm" :disabled="busy" @click="regenerate">
          {{ busy ? '生成中…' : '重置邀请码' }}
        </button>
      </div>

      <div class="stat-grid">
        <div class="card stat"><span class="hint">已邀请好友</span><strong class="mono">{{ summary.invited_count }}</strong></div>
        <div class="card stat"><span class="hint">已充值好友</span><strong class="mono">{{ summary.recharged_count }}</strong></div>
        <div class="card stat"><span class="hint">累计获得积分</span><strong class="mono">{{ summary.awarded_points }}</strong></div>
      </div>

      <div class="card">
        <h3>好友列表</h3>
        <p v-if="friends.length === 0" class="hint" role="status">
          还没有好友通过你的邀请注册。
        </p>
        <table v-else class="list">
          <thead><tr><th>好友邮箱</th><th>状态</th><th>你获得的奖励</th><th>注册时间</th></tr></thead>
          <tbody>
            <tr v-for="f in friends" :key="f.friend_email">
              <td>{{ f.friend_email }}</td>
              <td><span class="badge">{{ f.status === 'recharged' ? '已充值' : f.status === 'joined' ? '已注册' : '待注册' }}</span></td>
              <td>{{ f.points_awarded }}</td>
              <td>{{ fmt(f.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.rule { font-size: 14px; color: var(--fg); }
.warn-note { margin-top: 4px; }
.code-row { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; margin: 8px 0; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field.grow { flex: 1; min-width: 240px; }
.btn-col { display: flex; gap: 8px; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.stat { margin-bottom: 0; }
.stat strong { display: block; font-size: 22px; margin-top: 4px; }
</style>
