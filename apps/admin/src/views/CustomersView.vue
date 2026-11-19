<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, can, type CustomerRow } from '../api/client'

// 客户管理（03 §3.2）：状态变更（冻结/恢复）为高风险操作——弹窗写明理由后提交。
// RBAC：仅具备 customers:write 的角色可见操作按钮（后端权威校验）。
const canWrite = can('customers:write')
const items = ref<CustomerRow[]>([])
const total = ref(0)
const loading = ref(true)
const error = ref('')
const feedback = ref('')
const search = ref('')

const statusTarget = ref<CustomerRow | null>(null)
const nextStatus = ref<'active' | 'suspended' | 'deleted'>('suspended')
const reason = ref('')
const submittingStatus = ref(false)

onMounted(reload)

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.get<{ items: CustomerRow[]; total: number }>(
      '/api/v1/admin/customers',
      { limit: 100 },
    )
    items.value = data.items
    total.value = data.total
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

const filtered = computed(() =>
  items.value.filter((row) => {
    const q = search.value.trim().toLowerCase()
    if (!q) return true
    return row.email.toLowerCase().includes(q) || row.public_id.toLowerCase().includes(q)
  }),
)

function openStatusDialog(row: CustomerRow, status: 'active' | 'suspended' | 'deleted') {
  statusTarget.value = row
  nextStatus.value = status
  reason.value = ''
}

async function submitStatus() {
  if (!statusTarget.value || !reason.value.trim()) {
    feedback.value = ''
    error.value = '必须写明操作理由（审计要求）'
    return
  }
  submittingStatus.value = true
  error.value = ''
  try {
    await api.patch(
      `/api/v1/admin/customers/${statusTarget.value.customer_id}/status`,
      { status: nextStatus.value, reason: reason.value.trim() },
    )
    feedback.value = `客户 ${statusTarget.value.public_id.slice(0, 8)}… 已置为 ${nextStatus.value}`
    statusTarget.value = null
    await reload()
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    submittingStatus.value = false
  }
}

const statusBadgeClass: Record<string, string> = {
  active: 'ok',
  suspended: 'warn',
  deleted: 'err',
}
const statusLabelZh: Record<string, string> = {
  active: '正常',
  suspended: '已冻结',
  deleted: '已删除',
}
</script>

<template>
  <section>
    <h1 class="page-title">客户管理</h1>
    <p class="page-sub">查看客户列表与状态；冻结/恢复为高风险操作，需写明理由并记录审计。</p>

    <div class="card form-row">
      <div>
        <label for="cust-search" class="field-label">搜索客户</label>
        <input id="cust-search" v-model="search" placeholder="邮箱或客户 ID 片段" />
      </div>
    </div>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="feedback" class="ok-box" role="status">{{ feedback }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <table v-else-if="filtered.length" class="list">
      <thead>
        <tr>
          <th>客户 ID</th>
          <th>邮箱</th>
          <th>租户</th>
          <th>状态</th>
          <th>创建时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in filtered" :key="row.customer_id">
          <td class="mono">{{ row.public_id.slice(0, 8) }}…</td>
          <td>{{ row.email }}</td>
          <td class="mono">{{ row.tenant_id ?? '—' }}</td>
          <td>
            <span class="badge" :class="statusBadgeClass[row.status] ?? ''">
              {{ statusLabelZh[row.status] ?? row.status }}
            </span>
          </td>
          <td>{{ row.created_at ? new Date(row.created_at).toLocaleString() : '—' }}</td>
          <td>
            <template v-if="canWrite">
              <button
                v-if="row.status === 'active'"
                class="btn ghost sm"
                @click="openStatusDialog(row, 'suspended')"
              >冻结</button>
              <button
                v-else-if="row.status === 'suspended'"
                class="btn ghost sm"
                @click="openStatusDialog(row, 'active')"
              >恢复</button>
            </template>
            <span v-else class="hint">—</span>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-else class="card"><p class="hint" role="status">暂无客户记录。</p></div>

    <!-- 高风险操作确认（03 §3.1：记录操作者、对象、理由、前后状态） -->
    <div v-if="statusTarget" class="modal-mask" @click.self="statusTarget = null">
      <div class="modal card" role="dialog" aria-modal="true" aria-label="客户状态变更确认">
        <h3>确认{{ nextStatus === 'active' ? '恢复' : '冻结' }}客户</h3>
        <ul class="kv">
          <li><span>客户</span><span class="mono">{{ statusTarget.email }}</span></li>
          <li><span>当前状态</span><span>{{ statusLabelZh[statusTarget.status] }}</span></li>
          <li><span>目标状态</span><strong>{{ statusLabelZh[nextStatus] }}</strong></li>
        </ul>
        <label for="status-reason" class="field-label">操作理由（必填，写入审计）</label>
        <textarea id="status-reason" v-model="reason" rows="3" placeholder="例如：客户申请解封，工单 #123"></textarea>
        <div class="actions">
          <button class="btn" :class="{ danger: nextStatus !== 'active' }" :disabled="submittingStatus" @click="submitStatus">
            {{ submittingStatus ? '提交中…' : '确认执行' }}
          </button>
          <button class="btn ghost" @click="statusTarget = null">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.actions { display: flex; gap: 12px; margin-top: 12px; }
</style>
