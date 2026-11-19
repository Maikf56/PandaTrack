<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, can, type ProviderRow } from '../api/client'

// Provider 与任务运维（03 §3.3）：状态卡片 + 受控启停（理由必填 + 审计）。
// queue_snapshot 返回 {by_state, dead_letter} 聚合（修复旧版按数组解析恒为空的 bug）。
const canToggle = can('providers:write')
const providers = ref<ProviderRow[]>([])
const queue = ref<{ by_state: Record<string, number>; dead_letter: number } | null>(null)
const loading = ref(true)
const error = ref('')
const feedback = ref('')

const toggleTarget = ref<ProviderRow | null>(null)
const toggleEnabled = ref(false)
const toggleReason = ref('')
const submittingToggle = ref(false)

onMounted(reload)

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const [p, q] = await Promise.all([
      api.get<{ items: ProviderRow[] }>('/api/v1/admin/providers'),
      api.get<{ by_state: Record<string, number>; dead_letter: number }>('/api/v1/admin/tasks'),
    ])
    providers.value = p.items
    queue.value = q
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

function openToggle(row: ProviderRow) {
  toggleTarget.value = row
  toggleEnabled.value = !row.enabled
  toggleReason.value = ''
}

async function submitToggle() {
  if (!toggleTarget.value) return
  if (!toggleReason.value.trim()) {
    error.value = '必须写明操作理由（审计要求）'
    return
  }
  submittingToggle.value = true
  error.value = ''
  try {
    await api.post(
      `/api/v1/admin/providers/${toggleTarget.value.provider_code}/toggle`,
      undefined,
      { enabled: toggleEnabled.value, reason: toggleReason.value.trim() },
    )
    feedback.value = `Provider ${toggleTarget.value.provider_code} 已${toggleEnabled.value ? '启用' : '停用'}`
    toggleTarget.value = null
    await reload()
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    submittingToggle.value = false
  }
}

const QUEUE_STATE_ZH: Record<string, string> = {
  pending: '待处理', processing: '处理中', done: '已完成', failed: '失败',
  deferred: '已延期', suspended: '已暂停', dead_letter: '死信',
}

const queueLines = computed(() => {
  if (!queue.value) return []
  return Object.entries(queue.value.by_state)
    .map(([state, n]) => ({ state, zh: QUEUE_STATE_ZH[state] ?? state, n }))
    .sort((a, b) => b.n - a.n)
})

const pendingTotal = computed(() =>
  (queue.value?.by_state.pending ?? 0) + (queue.value?.by_state.processing ?? 0))

function fmtTime(v: string | null): string {
  if (!v) return '—'
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString()
}

function circuitZh(state: string | null | undefined): string {
  if (!state) return ''
  const map: Record<string, string> = { closed: '闭合（正常）', open: '打开（熔断中）', 'half-open': '半开（试探恢复）' }
  return map[state] ?? state
}

// 条形图宽度按对数缩放（避免单个巨量状态压扁其他行），最小 4% 保证可见
function queueBarWidth(n: number): string {
  const max = Math.max(...queueLines.value.map((l) => l.n), 1)
  const scaled = Math.log10(n + 1) / Math.log10(max + 1)
  return `${Math.max(4, Math.round(scaled * 100))}%`
}
</script>

<template>
  <section>
    <h1 class="page-title">Provider 与任务</h1>
    <p class="page-sub">
      采集通道健康与队列积压；启停为高风险操作，理由必填并写入审计（03 §3.3）。
    </p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="feedback" class="ok-box" role="status">{{ feedback }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <template v-else>
      <div class="prov-grid">
        <div v-for="p in providers" :key="p.provider_code" class="card prov-card"
             :class="{ 'prov-alert': (p.circuit_state && p.circuit_state !== 'closed') || !p.enabled }">
          <div class="prov-head">
            <span class="mono prov-code">{{ p.provider_code }}</span>
            <span class="badge" :class="p.enabled ? 'ok' : 'err'">
              {{ p.enabled ? '已启用' : '已停用' }}
            </span>
          </div>
          <p class="prov-line">
            <span class="hint">熔断器</span>
            <span class="badge" :class="p.circuit_state && p.circuit_state !== 'closed' ? 'err' : 'ok'">
              {{ circuitZh(p.circuit_state) || '未装配' }}
            </span>
          </p>
          <p class="prov-line">
            <span class="hint">最近成功</span>
            <span>{{ fmtTime(p.last_success_at) }}</span>
          </p>
          <p v-if="p.success_rate !== undefined && p.success_rate !== null" class="prov-line">
            <span class="hint">成功率</span>
            <span class="mono">{{ (Number(p.success_rate) * 100).toFixed(1) }}%</span>
          </p>
          <div class="prov-foot">
            <button v-if="canToggle" class="btn ghost sm" @click="openToggle(p)">
              {{ p.enabled ? '停用' : '启用' }}
            </button>
            <span v-else class="hint">只读</span>
          </div>
        </div>
        <div v-if="!providers.length" class="card">
          <p class="hint" role="status">暂无 Provider 记录。</p>
        </div>
      </div>

      <div class="card">
        <div class="queue-head">
          <h3>队列快照</h3>
          <span class="hint">
            在途（待处理 + 处理中）
            <strong class="mono" :class="{ 'is-alert': pendingTotal > 200 }">{{ pendingTotal }}</strong>
          </span>
        </div>
        <p v-if="!queueLines.length" class="hint" role="status">队列为空——没有任何待采集任务。</p>
        <div v-else class="queue-bars">
          <div v-for="l in queueLines" :key="l.state" class="queue-row">
            <span class="queue-label">{{ l.zh }}</span>
            <div class="queue-track">
              <div class="queue-fill" :class="{ 'fill-alert': l.state === 'dead_letter' || l.state === 'failed' }"
                   :style="{ width: queueBarWidth(l.n) }"></div>
            </div>
            <span class="mono queue-num">{{ l.n }}</span>
          </div>
        </div>
        <p v-if="queue && queue.dead_letter > 0" class="error-box" role="alert">
          有 {{ queue.dead_letter }} 条死信任务（多次重试仍失败），需要人工排查。
        </p>
      </div>
    </template>

    <!-- 受控启停确认（03 §3.3：未验收禁启用；理由必填 + 审计） -->
    <div v-if="toggleTarget" class="modal-mask" @click.self="toggleTarget = null">
      <div class="modal card" role="dialog" aria-modal="true" aria-label="Provider 启停确认">
        <h3>确认{{ toggleEnabled ? '启用' : '停用' }} Provider</h3>
        <ul class="kv">
          <li><span>Provider</span><span class="mono">{{ toggleTarget.provider_code }}</span></li>
          <li><span>目标状态</span><strong>{{ toggleEnabled ? '启用' : '停用' }}</strong></li>
        </ul>
        <p v-if="toggleEnabled" class="error-box" role="alert">
          仅允许对已通过验收配置的 Provider 启用；恢复后从最低已验证速率开始观察。
        </p>
        <label for="toggle-reason" class="field-label">操作理由（必填，写入审计）</label>
        <textarea id="toggle-reason" v-model="toggleReason" rows="3" placeholder="例如：出口代理恢复，工单 #789"></textarea>
        <div class="actions">
          <button class="btn" :disabled="submittingToggle" @click="submitToggle">
            {{ submittingToggle ? '提交中…' : '确认执行' }}
          </button>
          <button class="btn ghost" @click="toggleTarget = null">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.actions { display: flex; gap: 12px; margin-top: 12px; }

.prov-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px; margin-bottom: 16px;
}
.prov-card { margin-bottom: 0; display: flex; flex-direction: column; gap: 10px; }
.prov-card.prov-alert { border-color: #fecaca; background: var(--err-soft); }
.prov-head { display: flex; justify-content: space-between; align-items: center; }
.prov-code { font-weight: 700; font-size: 15px; }
.prov-line { display: flex; justify-content: space-between; align-items: center; margin: 0; font-size: 14px; }
.prov-foot { margin-top: auto; padding-top: 8px; }

.queue-head { display: flex; justify-content: space-between; align-items: baseline; }
.queue-head .is-alert { color: var(--err); }
.queue-bars { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
.queue-row { display: grid; grid-template-columns: 88px 1fr 64px; gap: 12px; align-items: center; }
.queue-label { font-size: 13px; color: var(--fg-soft); }
.queue-track { height: 10px; background: var(--bg); border-radius: 999px; overflow: hidden; }
.queue-fill { height: 100%; background: var(--brand); border-radius: 999px; transition: width 300ms ease-out; }
.queue-fill.fill-alert { background: var(--err); }
.queue-num { text-align: right; font-size: 13px; }
</style>
