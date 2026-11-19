<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type ProviderRow } from '../api/client'

// Provider 与任务运维（03 §3.3）：只读观察 + 受控启停（理由必填 + 审计）。
const providers = ref<ProviderRow[]>([])
const tasks = ref<Record<string, unknown>[]>([])
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
    const [p, t] = await Promise.all([
      api.get<{ items: ProviderRow[] }>('/api/v1/admin/providers'),
      api.get<{ items?: Record<string, unknown>[] } | Record<string, unknown>[]>('/api/v1/admin/tasks'),
    ])
    providers.value = p.items
    const tRaw = t as { items?: Record<string, unknown>[] }
    tasks.value = Array.isArray(t) ? t : (tRaw.items ?? [])
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

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') {
    const d = new Date(v)
    if (!Number.isNaN(d.getTime()) && v.includes('-')) return d.toLocaleString()
    return v
  }
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

const taskKeys = ref<string[]>([])
function deriveTaskKeys() {
  const keys = new Set<string>()
  for (const t of tasks.value) for (const k of Object.keys(t)) keys.add(k)
  taskKeys.value = [...keys].slice(0, 8)
}
deriveTaskKeys()
</script>

<template>
  <section>
    <h1 class="page-title">Provider 与任务</h1>
    <p class="page-sub">
      只读观察采集健康与队列；启停仅对已验收配置操作，理由必填并写入审计（03 §3.3）。
    </p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="feedback" class="ok-box" role="status">{{ feedback }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <template v-else>
      <div class="card">
        <h3>Provider 健康</h3>
        <p v-if="!providers.length" class="hint" role="status">暂无 Provider 记录。</p>
        <table v-else class="list">
          <thead>
            <tr><th>代码</th><th>状态</th><th>最近成功</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in providers" :key="p.provider_code">
              <td class="mono">{{ p.provider_code }}</td>
              <td>
                <span class="badge" :class="p.enabled ? 'ok' : 'err'">
                  {{ p.enabled ? '已启用' : '已停用' }}
                </span>
                <span v-if="p.circuit_state" class="badge warn" style="margin-left: 6px">
                  熔断：{{ fmt(p.circuit_state) }}
                </span>
              </td>
              <td>{{ p.last_success_at ? new Date(p.last_success_at).toLocaleString() : '—' }}</td>
              <td>
                <button class="btn ghost sm" @click="openToggle(p)">
                  {{ p.enabled ? '停用' : '启用' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>队列快照</h3>
        <p v-if="!tasks.length" class="hint" role="status">队列为空。</p>
        <table v-else class="list">
          <thead>
            <tr>
              <th v-for="k in taskKeys" :key="k">{{ k }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(t, i) in tasks" :key="i">
              <td v-for="k in taskKeys" :key="k" class="mono">{{ fmt(t[k]) }}</td>
            </tr>
          </tbody>
        </table>
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
</style>
