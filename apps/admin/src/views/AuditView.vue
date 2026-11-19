<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type AuditRow } from '../api/client'

// 审计日志（03 §3.4）：全部高风险操作的查询视图；按动作/对象过滤，详情可展开。
const items = ref<AuditRow[]>([])
const total = ref(0)
const loading = ref(true)
const error = ref('')
const actionFilter = ref('')
const expanded = ref<Set<number>>(new Set())

const ACTION_ZH: Record<string, string> = {
  customer_status_change: '客户状态变更',
  provider_toggle: 'Provider 启停',
  points_adjust: '积分调整',
}

onMounted(reload)

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.get<{ items: AuditRow[]; total: number }>(
      '/api/v1/admin/audit',
      { limit: 100, action: actionFilter.value || undefined },
    )
    items.value = data.items
    total.value = data.total
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

function toggleExpand(id: number) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function fmtDetail(d: Record<string, unknown> | null): string {
  if (!d || !Object.keys(d).length) return '—'
  return Object.entries(d).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join('\n')
}
</script>

<template>
  <section>
    <h1 class="page-title">审计日志</h1>
    <p class="page-sub">全部管理端操作的操作者、对象、理由与时间；不可篡改，只读查询。</p>

    <div class="card form-row">
      <div>
        <label for="audit-action" class="field-label">按动作过滤</label>
        <select id="audit-action" v-model="actionFilter" @change="reload">
          <option value="">全部动作</option>
          <option value="customer_status_change">客户状态变更</option>
          <option value="provider_toggle">Provider 启停</option>
          <option value="points_adjust">积分调整</option>
        </select>
      </div>
      <p class="hint" style="align-self: end">共 {{ total }} 条</p>
    </div>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <table v-else-if="items.length" class="list">
      <thead>
        <tr>
          <th>时间</th>
          <th>操作者</th>
          <th>动作</th>
          <th>对象</th>
          <th>详情</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in items" :key="row.audit_id">
          <td>{{ new Date(row.created_at).toLocaleString() }}</td>
          <td class="mono">{{ row.actor_role ?? '' }}/{{ row.actor_id ?? '—' }}</td>
          <td><span class="badge">{{ ACTION_ZH[row.action] ?? row.action }}</span></td>
          <td class="mono">{{ row.target ?? '—' }}</td>
          <td>
            <button
              v-if="row.detail && Object.keys(row.detail).length"
              class="btn ghost sm"
              @click="toggleExpand(row.audit_id)"
            >
              {{ expanded.has(row.audit_id) ? '收起' : '展开' }}
            </button>
            <span v-else class="hint">—</span>
            <pre v-if="expanded.has(row.audit_id)" class="detail-pre">{{ fmtDetail(row.detail) }}</pre>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-else class="card"><p class="hint" role="status">暂无审计记录——尚无管理端高风险操作发生。</p></div>
  </section>
</template>

<style scoped>
.detail-pre {
  margin: 8px 0 0; padding: 10px 12px; background: var(--bg);
  border: 1px solid var(--line); border-radius: var(--radius-ctl);
  white-space: pre-wrap; word-break: break-all; font-size: 12px;
  font-family: var(--mono); max-width: 320px;
}
</style>
