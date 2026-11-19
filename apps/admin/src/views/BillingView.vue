<script setup lang="ts">
import { ref } from 'vue'
import { api, type LedgerRow } from '../api/client'

// 账务操作（03 §3.2）：积分调整只追加 PointsLedger（不直接 patch 余额）；
// 高风险操作——理由必填 + 弹窗二次确认 + 强制审计。
const customerId = ref('')
const delta = ref<number | null>(null)
const description = ref('')
const reason = ref('')
const submitting = ref(false)
const error = ref('')
const feedback = ref('')

const confirmOpen = ref(false)
const adjustResult = ref<Record<string, unknown> | null>(null)

const ledgerRows = ref<LedgerRow[]>([])
const ledgerCustomer = ref('')
const ledgerLoading = ref(false)

function openConfirm() {
  error.value = ''
  if (!customerId.value.trim()) {
    error.value = '请输入客户 ID（数字内部 ID 或 UUID）'
    return
  }
  if (!delta.value || delta.value === 0) {
    error.value = '调整幅度不能为 0'
    return
  }
  if (!description.value.trim()) {
    error.value = '必须填写调整说明'
    return
  }
  if (!reason.value.trim()) {
    error.value = '必须填写操作理由（审计要求）'
    return
  }
  adjustResult.value = null
  confirmOpen.value = true
}

async function submitAdjust() {
  confirmOpen.value = false
  submitting.value = true
  error.value = ''
  try {
    const data = await api.post<Record<string, unknown>>(
      '/api/v1/admin/billing/adjust',
      undefined,
      {
        customer_id: customerId.value.trim(),
        delta: delta.value ?? 0,
        description: description.value.trim(),
        reason: reason.value.trim(),
      },
    )
    adjustResult.value = data
    feedback.value = `积分调整已入账并写入审计流水。`
    await loadLedger()
  } catch (e) {
    error.value = (e as { message: string }).message
    feedback.value = ''
  } finally {
    submitting.value = false
  }
}

async function loadLedger() {
  if (!customerId.value.trim()) return
  ledgerLoading.value = true
  try {
    const data = await api.get<{ items: LedgerRow[] }>('/api/v1/admin/billing/ledger', {
      customer_id: customerId.value.trim(),
      limit: 20,
    })
    ledgerRows.value = data.items
    ledgerCustomer.value = customerId.value.trim()
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    ledgerLoading.value = false
  }
}

const ledgerTypeZh: Record<string, string> = {
  charge: '提交扣费',
  topup: '充值',
  bonus: '赠送',
  adjust: '人工调整',
  reversal: '冲正/退款',
}
</script>

<template>
  <section>
    <h1 class="page-title">账务操作</h1>
    <p class="page-sub">
      积分调整只追加流水记录，不直接修改钱包余额；每笔操作强制审计（03 §3.2）。
    </p>

    <div class="card">
      <h3>积分调整</h3>
      <div class="form-row">
        <div>
          <label for="adj-cust" class="field-label">客户 ID</label>
          <input id="adj-cust" v-model="customerId" class="mono" placeholder="内部数字 ID" />
        </div>
        <div>
          <label for="adj-delta" class="field-label">调整幅度（正加负减）</label>
          <input id="adj-delta" v-model.number="delta" type="number" class="mono" placeholder="例如 100 或 -50" />
        </div>
        <div>
          <label for="adj-desc" class="field-label">调整说明</label>
          <input id="adj-desc" v-model="description" placeholder="例如：故障补偿" />
        </div>
        <div>
          <label for="adj-reason" class="field-label">操作理由（审计）</label>
          <input id="adj-reason" v-model="reason" placeholder="例如：工单 #456" />
        </div>
      </div>
      <p v-if="error" class="error-box" role="alert">{{ error }}</p>
      <p v-if="feedback" class="ok-box" role="status">{{ feedback }}</p>
      <div class="actions">
        <button class="btn" :disabled="submitting" @click="openConfirm">
          {{ submitting ? '提交中…' : '提交调整' }}
        </button>
        <button class="btn ghost" @click="loadLedger">查询该客户流水</button>
      </div>
    </div>

    <!-- 高风险操作确认（03 §3.1） -->
    <div v-if="confirmOpen" class="modal-mask" @click.self="confirmOpen = false">
      <div class="modal card" role="dialog" aria-modal="true" aria-label="积分调整确认">
        <h3>确认积分调整</h3>
        <ul class="kv">
          <li><span>客户 ID</span><span class="mono">{{ customerId }}</span></li>
          <li>
            <span>调整幅度</span>
            <strong class="mono" :style="{ color: (delta ?? 0) > 0 ? 'var(--ok)' : 'var(--err)' }">
              {{ (delta ?? 0) > 0 ? '+' : '' }}{{ delta }} 积分
            </strong>
          </li>
          <li><span>说明</span><span>{{ description }}</span></li>
          <li><span>理由</span><span>{{ reason }}</span></li>
        </ul>
        <p class="hint">确认后将追加 PointsLedger 流水并写入审计日志；不可通过本页面直接改余额。</p>
        <div class="actions">
          <button class="btn" :class="{ danger: (delta ?? 0) < 0 }" @click="submitAdjust">确认执行</button>
          <button class="btn ghost" @click="confirmOpen = false">取消</button>
        </div>
      </div>
    </div>

    <div v-if="adjustResult" class="card">
      <h3>调整结果</h3>
      <pre class="mono result-pre">{{ JSON.stringify(adjustResult, null, 2) }}</pre>
    </div>

    <div class="card">
      <h3>客户积分流水{{ ledgerCustomer ? `（客户 ${ledgerCustomer}）` : '' }}</h3>
      <p v-if="ledgerLoading" class="hint" role="status">正在加载…</p>
      <p v-else-if="!ledgerRows.length" class="hint" role="status">
        暂无流水。输入客户 ID 后点「查询该客户流水」。
      </p>
      <table v-else class="list">
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
.result-pre { margin: 0; white-space: pre-wrap; font-size: 13px; }
</style>
