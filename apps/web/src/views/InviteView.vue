<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, type InviteSummary, type InviteFriendView } from '../api/client'
import { loadSession } from '../composables/session'
import { t } from '../i18n'

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
    notice.value = t('invite.reset_done')
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    busy.value = false
  }
}

async function copy(text: string) {
  await navigator.clipboard?.writeText(text)
  notice.value = t('invite.copied')
}

function fmt(s?: string): string {
  return s ? new Date(s).toLocaleString() : '—'
}
</script>

<template>
  <section>
    <h1 class="page-title">{{ t('invite.title') }}</h1>
    <p class="page-sub">{{ t('invite.sub') }}</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="notice" class="ok-box" role="status">{{ notice }}</p>
    <p v-if="loading" class="hint" role="status">{{ t('common.loading') }}</p>

    <template v-else-if="summary">
      <div class="card">
        <h3>{{ t('invite.code_title') }}</h3>
        <p class="hint rule">
          {{ t('invite.rule') }}
          <strong>{{ 1000 }}{{ t('invite.bonus_points') }}</strong>{{ t('invite.rule_bonus') }}
          <strong>10%</strong> {{ t('invite.rule_percent') }}
        </p>
        <p class="hint warn-note">
          {{ t('invite.warn') }}
        </p>
        <div class="code-row">
          <div class="field">
            <span class="hint">{{ t('invite.code') }}</span>
            <input :value="summary.code" readonly class="mono" />
          </div>
          <div class="field grow">
            <span class="hint">{{ t('invite.link') }}</span>
            <input :value="link" readonly class="mono" />
          </div>
          <div class="btn-col">
            <button class="btn sm" @click="copy(summary.code)">{{ t('invite.copy_code') }}</button>
            <button class="btn sm ghost" @click="copy(link)">{{ t('invite.copy_link') }}</button>
          </div>
        </div>
        <button class="btn ghost sm" :disabled="busy" @click="regenerate">
          {{ busy ? t('exports.generating') : t('invite.reset') }}
        </button>
      </div>

      <div class="stat-grid">
        <div class="card stat"><span class="hint">{{ t('invite.stat_invited') }}</span><strong class="mono">{{ summary.invited_count }}</strong></div>
        <div class="card stat"><span class="hint">{{ t('invite.stat_recharged') }}</span><strong class="mono">{{ summary.recharged_count }}</strong></div>
        <div class="card stat"><span class="hint">{{ t('invite.stat_points') }}</span><strong class="mono">{{ summary.awarded_points }}</strong></div>
      </div>

      <div class="card">
        <h3>{{ t('invite.friends_title') }}</h3>
        <p v-if="friends.length === 0" class="hint" role="status">
          {{ t('invite.no_friends') }}
        </p>
        <table v-else class="list">
          <thead><tr><th>{{ t('invite.th.email') }}</th><th>{{ t('invite.th.status') }}</th><th>{{ t('invite.th.reward') }}</th><th>{{ t('invite.th.signed_up_at') }}</th></tr></thead>
          <tbody>
            <tr v-for="f in friends" :key="f.friend_email">
              <td>{{ f.friend_email }}</td>
              <td><span class="badge">{{ f.status === 'recharged' ? t('invite.status.recharged') : f.status === 'joined' ? t('invite.status.joined') : t('invite.status.pending') }}</span></td>
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
