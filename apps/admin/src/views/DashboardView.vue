<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, can, type CustomerRow, type ProviderRow, type AuditRow } from '../api/client'

// 总览（管理员首屏——值班巡查）：系统此刻健康吗？异常可点击直达对应页面。
// 数据全部来自既有端点，本页零后端改动。
const loading = ref(true)
const error = ref('')

const customers = ref<CustomerRow[]>([])
const customerTotal = ref(0)
const providers = ref<ProviderRow[]>([])
const queue = ref<{ by_state: Record<string, number>; dead_letter: number } | null>(null)
const recentAudit = ref<AuditRow[]>([])

const canReadCustomers = can('customers:read')
const canReadProviders = can('providers:read')
const canReadAudit = can('audit:read')

onMounted(reload)

async function reload() {
  loading.value = true
  error.value = ''
  const jobs: Promise<unknown>[] = []
  if (canReadCustomers) {
    jobs.push(api.get<{ items: CustomerRow[]; total: number }>(
      '/api/v1/admin/customers', { limit: 100 })
      .then((d) => { customers.value = d.items; customerTotal.value = d.total }))
  }
  if (canReadProviders) {
    jobs.push(api.get<{ items: ProviderRow[] }>('/api/v1/admin/providers')
      .then((d) => { providers.value = d.items }))
    jobs.push(api.get<{ by_state: Record<string, number>; dead_letter: number }>(
      '/api/v1/admin/tasks')
      .then((d) => { queue.value = d }))
  }
  if (canReadAudit) {
    jobs.push(api.get<{ items: AuditRow[] }>('/api/v1/admin/audit', { limit: 6 })
      .then((d) => { recentAudit.value = d.items }))
  }
  try {
    await Promise.all(jobs)
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

// ---- 派生指标 ----

const activeCount = computed(() =>
  customers.value.filter((c) => c.status === 'active').length)
const suspendedCount = computed(() =>
  customers.value.filter((c) => c.status === 'suspended').length)
const enabledProviders = computed(() =>
  providers.value.filter((p) => p.enabled).length)
const circuitTripped = computed(() =>
  providers.value.filter((p) => p.enabled && p.circuit_state && p.circuit_state !== 'closed'))

const QUEUE_STATE_ZH: Record<string, string> = {
  pending: '待处理',
  processing: '处理中',
  done: '已完成',
  failed: '失败',
  deferred: '已延期',
  suspended: '已暂停',
  dead_letter: '死信',
}
const queueLines = computed(() => {
  if (!queue.value) return []
  return Object.entries(queue.value.by_state)
    .filter(([, n]) => n > 0)
    .map(([state, n]) => ({ state, zh: QUEUE_STATE_ZH[state] ?? state, n }))
    .sort((a, b) => b.n - a.n)
})
const pendingTotal = computed(() =>
  (queue.value?.by_state.pending ?? 0) + (queue.value?.by_state.processing ?? 0))

// 队列积压判定：pending 超过 200 视为积压预警（USPS 采集节流下的经验阈值）
const queueBacklog = computed(() => pendingTotal.value > 200)

const AUDIT_ACTION_ZH: Record<string, string> = {
  customer_status_change: '客户状态变更',
  provider_toggle: 'Provider 启停',
  points_adjust: '积分调整',
}

function fmtTime(v: string | null): string {
  if (!v) return '—'
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString()
}
</script>

<template>
  <section>
    <h1 class="page-title">总览</h1>
    <p class="page-sub">系统此刻健康状态；红色项需要处理，点击卡片直达对应页面。</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <template v-else>
      <div class="stat-grid">
        <RouterLink v-if="canReadCustomers" to="/customers" class="stat-card linkable">
          <p class="stat-label">客户</p>
          <p class="stat-value">{{ customerTotal }}</p>
          <p class="stat-sub">
            <span class="badge ok">正常 {{ activeCount }}</span>
            <span v-if="suspendedCount" class="badge warn">冻结 {{ suspendedCount }}</span>
            <span v-else class="stat-sub-plain">冻结 0</span>
          </p>
        </RouterLink>

        <RouterLink v-if="canReadProviders" to="/providers" class="stat-card linkable"
                    :class="{ alert: queueBacklog || circuitTripped.length }">
          <p class="stat-label">采集队列</p>
          <p class="stat-value" :class="{ 'is-alert': queueBacklog }">
            {{ pendingTotal }}
          </p>
          <p class="stat-sub">
            <span v-if="queueBacklog" class="badge err">积压预警</span>
            <span v-else class="badge ok">运转正常</span>
            <span v-if="queue && queue.dead_letter" class="badge err">死信 {{ queue.dead_letter }}</span>
          </p>
          <ul v-if="queueLines.length" class="stat-lines">
            <li v-for="l in queueLines" :key="l.state">
              <span>{{ l.zh }}</span><span class="mono">{{ l.n }}</span>
            </li>
          </ul>
        </RouterLink>

        <RouterLink v-if="canReadProviders" to="/providers" class="stat-card linkable"
                    :class="{ alert: circuitTripped.length }">
          <p class="stat-label">Provider</p>
          <p class="stat-value">
            {{ enabledProviders }}<span class="stat-unit">/{{ providers.length }} 启用</span>
          </p>
          <p class="stat-sub">
            <span v-if="circuitTripped.length" class="badge err">熔断 {{ circuitTripped.length }}</span>
            <span v-else-if="providers.length" class="badge ok">全部正常</span>
            <span v-else class="badge warn">无数据</span>
          </p>
        </RouterLink>
      </div>

      <div v-if="canReadAudit" class="card">
        <div class="card-head">
          <h3>最近管理操作</h3>
          <RouterLink to="/audit" class="hint">查看全部 →</RouterLink>
        </div>
        <p v-if="!recentAudit.length" class="hint" role="status">暂无高风险操作记录——近期风平浪静。</p>
        <ul v-else class="audit-mini">
          <li v-for="a in recentAudit" :key="a.audit_id">
            <span class="badge">{{ AUDIT_ACTION_ZH[a.action] ?? a.action }}</span>
            <span class="mono target">{{ a.target ?? '—' }}</span>
            <span class="hint">{{ a.actor_role }} · {{ fmtTime(a.created_at) }}</span>
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>

<style scoped>
.stat-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px; margin-bottom: 16px;
}
.stat-card {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: var(--radius-panel); padding: 18px 20px; text-decoration: none;
  color: inherit; transition: box-shadow var(--dur) ease-out, border-color var(--dur) ease-out;
}
.stat-card.linkable:hover { box-shadow: var(--shadow-1); border-color: var(--brand); }
.stat-card.alert { border-color: #fecaca; background: var(--err-soft); }
.stat-label { color: var(--fg-soft); font-size: 13px; margin: 0 0 6px; font-weight: 600; }
.stat-value { font-size: 34px; font-weight: 700; margin: 0; line-height: 1.15; }
.stat-value.is-alert { color: var(--err); }
.stat-unit { font-size: 15px; font-weight: 500; color: var(--fg-soft); margin-left: 4px; }
.stat-sub { margin: 8px 0 0; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.stat-sub-plain { color: var(--fg-soft); font-size: 13px; }
.stat-lines { list-style: none; margin: 10px 0 0; padding: 0; font-size: 13px; }
.stat-lines li { display: flex; justify-content: space-between; padding: 3px 0; }
.card-head { display: flex; justify-content: space-between; align-items: baseline; }
.card-head a { text-decoration: none; }
.audit-mini { list-style: none; margin: 8px 0 0; padding: 0; }
.audit-mini li {
  display: flex; gap: 12px; align-items: baseline; padding: 8px 0;
  border-bottom: 1px dashed var(--line); flex-wrap: wrap;
}
.audit-mini li:last-child { border-bottom: none; }
.audit-mini .target { flex: 1; min-width: 120px; }
</style>
