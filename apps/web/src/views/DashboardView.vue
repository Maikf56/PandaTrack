<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api, type LedgerEntry, type TrackingView, type OperationSummary } from '../api/client'
import { loadSession, session, loadStatusDict } from '../composables/session'
import { useSse, visibilityPolling } from '../composables/sse'
import { t } from '../i18n'
import { splitDraft } from '../logic/draft'

// 工作台首页（04 §5.5）：现在需要关注什么 + 我刚才做了什么。
// SSE + 可见性感知轮询；事件到达只提示，客户点击才刷新（04 §6.3）。
const { hasUpdate, open, close } = useSse()
const loading = ref(true)
const error = ref('')
const recentLedger = ref<LedgerEntry[]>([])
const recentResults = ref<TrackingView[]>([])
const recentOps = ref<OperationSummary[]>([])
const quickInput = ref('')

onMounted(async () => {
  await loadSession(true)
  await loadStatusDict()
  try {
    const [w, tk, o] = await Promise.all([
      api.get<LedgerEntry[]>('/api/v1/billing/ledger', { limit: 5 }),
      api.get<TrackingView[]>('/api/v1/trackings'),
      api.get<OperationSummary[]>('/api/v1/operations', { limit: 5 }).catch(() => ({ data: [] as OperationSummary[] })),
    ])
    recentLedger.value = w.data
    recentResults.value = tk.data.slice(0, 5)
    recentOps.value = o.data.slice(0, 5)
    open() // 数据就绪后再订阅，重连由 EventSource 自动处理
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
})

const stopPolling = visibilityPolling(async () => {
  // 轻量摘要轮询：SSE 离线时兜底拉取最新结果（只读，不扣费）
  try {
    const { data } = await api.get<TrackingView[]>('/api/v1/trackings')
    recentResults.value = data.slice(0, 5)
  } catch {
    /* 静默，保留现有内容 */
  }
}, 20000)

onUnmounted(() => {
  stopPolling()
  close()
})

async function refreshResults() {
  hasUpdate.value = false
  try {
    const { data } = await api.get<TrackingView[]>('/api/v1/trackings')
    recentResults.value = data.slice(0, 5)
  } catch {
    /* 静默，保留现有内容 */
  }
}

const me = computed(() => session.me)

// 第一行摘要卡（04 §5.5）：余额 / 处理中 / 异常或暂未获取 / 已完成
const processingCount = computed(() =>
  recentOps.value.filter((o) => o.state === 'accepted' || o.state === 'processing').length,
)
const anomalyCount = computed(
  () => recentResults.value.filter((it) => !it.is_terminal && it.label_zh).length,
)
const doneCount = computed(
  () => recentResults.value.filter((it) => it.is_terminal).length,
)

const quickDraft = computed(() => splitDraft(quickInput.value))

function stateText(s: string): string {
  if (s === 'accepted') return t('common.state.accepted')
  if (s === 'processing') return t('common.state.processing')
  if (s === 'completed') return t('common.state.completed')
  if (s === 'failed') return t('common.state.failed')
  return s
}
</script>

<template>
  <section>
    <h1 class="page-title">{{ t('dash.title') }}</h1>
    <p class="page-sub">{{ t('dash.sub') }}</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">{{ t('common.loading') }}</p>

    <template v-else>
      <div class="cards-row">
        <div class="card stat">
          <p class="stat-label">{{ t('dash.stat.balance') }}</p>
          <p class="stat-num mono" role="status">{{ me?.balance ?? '—' }}</p>
        </div>
        <div class="card stat">
          <p class="stat-label">{{ t('dash.stat.processing') }}</p>
          <p class="stat-num mono">{{ processingCount }}</p>
        </div>
        <div class="card stat">
          <p class="stat-label">{{ t('dash.stat.nonterminal') }}</p>
          <p class="stat-num mono">{{ anomalyCount }}</p>
        </div>
        <div class="card stat">
          <p class="stat-label">{{ t('dash.stat.terminal') }}</p>
          <p class="stat-num mono">{{ doneCount }}</p>
        </div>
      </div>

      <div class="card main-actions">
        <RouterLink class="btn" to="/submit">{{ t('nav.submit') }}</RouterLink>
        <RouterLink class="btn ghost" to="/quick">{{ t('nav.quick') }}</RouterLink>
        <RouterLink class="btn ghost" to="/results">{{ t('nav.results') }}</RouterLink>
      </div>

      <!-- 快捷查询输入（04 §5.5 第二行） -->
      <div class="card quick-card">
        <label for="dash-quick" class="field-label">{{ t('dash.quick_label') }}</label>
        <input
          id="dash-quick"
          v-model="quickInput"
          class="mono"
          :placeholder="t('dash.quick_placeholder')"
          @keydown.enter.exact="quickDraft.totalLines > 0 && $router.push({ name: 'quick' })"
        />
        <p v-if="quickDraft.totalLines > 0" class="hint" role="status">
          {{ t('common.received', { n: quickDraft.totalLines }) }}
          <template v-if="quickDraft.totalLines > 35">{{ t('dash.over35') }}</template>
        </p>
      </div>

      <!-- SSE 有更新：轻提示，客户点击才刷新（04 §8.2/§6.3） -->
      <div v-if="hasUpdate" class="card sse-hint" role="status">
        {{ t('dash.sse') }}
        <button class="btn sm" @click="refreshResults">{{ t('dash.sse_refresh') }}</button>
      </div>

      <div class="card">
        <h3>{{ t('dash.recent_ops') }}</h3>
        <p v-if="recentOps.length === 0" class="hint" role="status">
          {{ t('dash.empty_ops') }}
        </p>
        <table v-else class="list">
          <thead>
            <tr><th>{{ t('common.th.op_id') }}</th><th>{{ t('common.th.count') }}</th><th>{{ t('common.th.charge') }}</th><th>{{ t('common.th.status') }}</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="op in recentOps" :key="op.id">
              <td class="mono">{{ op.id.slice(0, 8) }}…</td>
              <td class="mono">{{ op.total_count }}</td>
              <td class="mono">{{ op.points_charged }}</td>
              <td>{{ stateText(op.state) }}</td>
              <td><RouterLink :to="`/results?op=${op.id}`">{{ t('common.view_progress') }}</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>{{ t('dash.recent_results') }}</h3>
        <p v-if="recentResults.length === 0" class="hint" role="status">
          {{ t('dash.empty_ops') }}
        </p>
        <table v-else class="list">
          <thead>
            <tr><th>{{ t('common.th.number') }}</th><th>{{ t('common.th.status') }}</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="it in recentResults" :key="it.id">
              <td class="mono">{{ it.normalized_number }}</td>
              <td><span class="badge" :class="{ terminal: it.is_terminal }">{{ it.label_zh }}</span></td>
              <td><RouterLink :to="`/results/${it.id}`">{{ t('common.detail') }}</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.cards-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.stat-num { font-size: 28px; font-weight: 700; margin: 4px 0; }
.stat-label { color: var(--fg-soft); font-size: 13px; margin: 0; }
.main-actions { display: flex; gap: 12px; flex-wrap: wrap; }
.quick-card input { max-width: 640px; }
.sse-hint { display: flex; align-items: center; gap: 12px; border-left: 3px solid var(--ok); }
@media (max-width: 860px) {
  .cards-row { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 480px) {
  .cards-row { grid-template-columns: 1fr; }
  .quick-card input { max-width: none; }
}
</style>
