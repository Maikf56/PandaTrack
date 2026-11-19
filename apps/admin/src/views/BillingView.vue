<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api, can, type CustomerRow, type LedgerRow } from '../api/client'

// 账务操作（03 §3.2）：客户下拉选择（不再手输内部 ID）→ 余额/流水联动；
// 积分调整只追加 PointsLedger（不直接 patch 余额），理由必填 + 二次确认 + 审计。
// RBAC：billing:write 控调整表单；客户下拉复用 customers:read（矩阵内两角色均具备）。
const canWrite = can('billing:write')

const customers = ref<CustomerRow[]>([])
const customersLoading = ref(true)
const selectedId = ref<number | null>(null)

const ledgerRows = ref<LedgerRow[]>([])
const ledgerLoading = ref(false)
const ledgerLoaded = ref(false)

const adjustOpen = ref(false)
const adjustDelta = ref<number | null>(null)
const adjustDesc = ref('')
const adjustReason = ref('')
const submitting = ref(false)
const error = ref('')
const feedback = ref('')

onMounted(async () => {
  try {
    const data = await api.get<{ items: CustomerRow[]; total: number }>(
      '/api/v1/admin/customers', { limit: 100 })
    customers.value = data.items
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    customersLoading.value = false
  }
})

const selected = computed(() =>
  customers.value.find((c) => c.customer_id === selectedId.value) ?? null)

async function loadLedger() {
  if (!selectedId.value) return
  ledgerLoading.value = true
  error.value = ''
  try {
    const data = await api.get<{ items: LedgerRow[] }>('/api/v1/admin/billing/ledger', {
      customer_id: selectedId.value,
      limit: 20,
    })
    ledgerRows.value = data.items
    ledgerLoaded.value = true
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    ledgerLoading.value = false
  }
}

function openConfirm() {
  error.value = ''
  if (!selected.value) {
    error.value = '请先选择客户'
    return
  }
  if (!adjustDelta.value || adjustDelta.value === 0) {
    error.value = '调整幅度不能为 0'
    return
  }
  if (!adjustDesc.value.trim()) {
    error.value = '必须填写调整说明'
    return
  }
  if (!adjustReason.value.trim()) {
    error.value = '必须填写操作理由（审计要求）'
    return
  }
  adjustOpen.value = true
}

async function submitAdjust() {
  adjustOpen.value = false
  const cid = selectedId.value
  if (!cid) return
  submitting.value = true
  error.value = ''
  try {
    await api.post('/api/v1/admin/billing/adjust', undefined, {
      customer_id: cid,
      delta: adjustDelta.value ?? 0,
      description: adjustDesc.value.trim(),
      reason: adjustReason.value.trim(),
    })
    feedback.value = `客户 ${selected.value?.email} 积分调整已入账并写入审计流水`
    adjustDelta.value = null
    adjustDesc.value = ''
    adjustReason.value = ''
    await loadLedger()
  } catch (e) {
    error.value = (e as { message: string }).message
    feedback.value = ''
  } finally {
    submitting.value = false
  }
}

const ledgerTypeZh: Record<string, string> = {
  charge: '提交扣费', topup: '充值', bonus: '赠送', adjust: '人工调整', reversal: '冲正/退款',
}
</script>

<template>
  <section>
    <h1 class="page-title">账务操作</h1>
    <p class="page-sub">
      积分调整只追加流水记录，不直接修改钱包余额；每笔操作强制审计（03 §3.2）。
    </p>

    <div class="card">
      <label for="bill-cust" class="field-label">选择客户</label>
      <select id="bill-cust" v-model.number="selectedId" :disabled="customersLoading" @change="loadLedger">
        <option :value="null" disabled>{{ customersLoading ? '正在加载客户…' : '请选择客户' }}</option>
        <option v-for="c in customers" :key="c.customer_id" :value="c.customer_id">
          {{ c.email }}（余额 {{ c.balance ?? 0 }} · {{ c.status === 'active' ? '正常' : c.status === 'suspended' ? '已冻结' : c.status }}）
        </option>
      </select>

      <div v-if="selected" class="sel-balance">
        <span class="hint">当前余额</span>
        <strong class="mono">{{ selected.balance ?? 0 }} 积分</strong>
      </div>
    </div>

    <div v-if="canWrite && selected" class="card">
      <h3>积分调整</h3>
      <div class="form-row">
        <div>
          <label for="adj-delta" class="field-label">调整幅度（正加负减）</label>
          <input id="adj-delta" v-model.number="adjustDelta" type="number" class="mono" placeholder="例如 100 或 -50" />
        </div>
        <div>
          <label for="adj-desc" class="field-label">调整说明</label>
          <input id="adj-desc" v-model="adjustDesc" placeholder="例如：故障补偿" />
        </div>
        <div>
          <label for="adj-reason" class="field-label">操作理由（审计）</label>
          <input id="adj-reason" v-model="adjustReason" placeholder="例如：工单 #456" />
        </div>
      </div>
      <p v-if="error" class="error-box" role="alert">{{ error }}</p>
      <p v-if="feedback" class="ok-box" role="status">{{ feedback }}</p>
      <div class="actions">
        <button class="btn" :disabled="submitting" @click="openConfirm">
          {{ submitting ? '提交中…' : '提交调整' }}
        </button>
      </div>
    </div>
    <p v-else-if="!canWrite" class="hint">当前角色为只读账务视角，仅可查询流水。</p>

    <!-- 高风险操作确认（03 §3.1） -->
    <div v-if="adjustOpen" class="modal-mask" @click.self="adjustOpen = false">
      <div class="modal card" role="dialog" aria-modal="true" aria-label="积分调整确认">
        <h3>确认积分调整</h3>
        <ul class="kv">
          <li><span>客户</span><span class="mono">{{ selected?.email }}</span></li>
          <li><span>当前余额</span><span class="mono">{{ selected?.balance ?? 0 }} 积分</span></li>
          <li>
            <span>调整幅度</span>
            <strong class="mono" :style="{ color: (adjustDelta ?? 0) > 0 ? 'var(--ok)' : 'var(--err)' }">
              {{ (adjustDelta ?? 0) > 0 ? '+' : '' }}{{ adjustDelta }} 积分
            </strong>
          </li>
          <li><span>说明</span><span>{{ adjustDesc }}</span></li>
          <li><span>理由</span><span>{{ adjustReason }}</span></li>
        </ul>
        <p class="hint">确认后将追加 PointsLedger 流水并写入审计日志；不可通过本页面直接改余额。</p>
        <div class="actions">
          <button class="btn" :class="{ danger: (adjustDelta ?? 0) < 0 }" @click="submitAdjust">确认执行</button>
          <button class="btn ghost" @click="adjustOpen = false">取消</button>
        </div>
      </div>
    </div>

    <div v-if="selectedId" class="card">
      <h3>积分流水</h3>
      <p v-if="ledgerLoading" class="hint" role="status">正在加载…</p>
      <p v-else-if="!ledgerRows.length && ledgerLoaded" class="hint" role="status">该客户暂无流水记录。</p>
      <table v-else-if="ledgerRows.length" class="list">
        <thead>
          <tr><th>类型</th><th>变动</th><th>说明</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in ledgerRows" :key="r.ledger_id">
            <td>{{ ledgerTypeZh[r.ledger_type] ?? r.ledger_type }}</td>
            <td class="mono" :style="{ color: r.points_change > 0 ? 'var(--ok)' : 'var(--err)' }">
              {{ r.points_change > 0 ? '+' : '' }}{{ r.points_change }}
            </td>
            <td>{{ r.description ?? '—' }}</td>
            <td>{{ new Date(r.created_at).toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.actions { display: flex; gap: 12px; margin-top: 12px; }
.sel-balance {
  display: flex; gap: 10px; align-items: baseline; margin-top: 12px;
  padding-top: 12px; border-top: 1px dashed var(--line);
}
.sel-balance strong { font-size: 18px; }
</style>
