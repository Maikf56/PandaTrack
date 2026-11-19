<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type BillingSummary, type LedgerEntry } from '../api/client'
import { loadSession } from '../composables/session'

// 积分中心（04 §5.11）：余额/冻结/消耗 + 流水 + 兑换码。余额来自服务端。
const loading = ref(true)
const error = ref('')
const summary = ref<BillingSummary | null>(null)
const ledger = ref<LedgerEntry[]>([])
const redeemCode = ref('')
const redeeming = ref(false)
const redeemMsg = ref('')
const redeemErr = ref('')

onMounted(async () => {
  await loadSession(true)
  await reload()
})

async function reload() {
  loading.value = true
  try {
    const [s, l] = await Promise.all([
      api.get<BillingSummary>('/api/v1/billing/wallet'),
      api.get<LedgerEntry[]>('/api/v1/billing/ledger', { limit: 100 }),
    ])
    summary.value = s.data
    ledger.value = l.data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

const LEDGER_LABEL: Record<string, string> = {
  charge: '扣费',
  refund: '冲正/退款',
  redeem: '兑换充值',
  admin_adjust: '管理员调整',
}

async function redeem() {
  if (redeeming.value) return
  redeemMsg.value = ''
  redeemErr.value = ''
  const code = redeemCode.value.trim().toUpperCase()
  if (!/^[A-Z0-9]{4}(-[A-Z0-9]{4}){2}$/.test(code)) {
    redeemErr.value = '兑换码格式应为 XXXX-XXXX-XXXX'
    return
  }
  redeeming.value = true
  try {
    await api.post('/api/v1/billing/redemptions', { code })
    redeemMsg.value = '兑换成功，余额已更新。'
    redeemCode.value = ''
    await Promise.all([reload(), loadSession(true)])
  } catch (e) {
    redeemErr.value = (e as { message: string }).message
  } finally {
    redeeming.value = false
  }
}
</script>

<template>
  <section>
    <h1 class="page-title">积分中心</h1>
    <p class="page-sub">查看余额、冻结、消耗与流水；余额以服务端为准。</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <template v-if="summary">
      <div class="cards-row">
        <div class="card stat">
          <p class="stat-label">当前余额</p>
          <p class="stat-num" role="status">{{ summary.balance }}</p>
        </div>
        <div class="card stat">
          <p class="stat-label">处理中冻结</p>
          <p class="stat-num">{{ summary.frozen }}</p>
        </div>
        <div class="card stat">
          <p class="stat-label">累计消耗</p>
          <p class="stat-num">{{ summary.lifetime_consumed }}</p>
        </div>
      </div>

      <div class="card">
        <h3>兑换码</h3>
        <form class="redeem-row" @submit.prevent="redeem">
          <label for="redeem-code" class="sr-only">兑换码</label>
          <input
            id="redeem-code"
            v-model="redeemCode"
            class="mono"
            placeholder="XXXX-XXXX-XXXX"
            style="max-width: 260px"
          />
          <button class="btn" type="submit" :disabled="redeeming">
            {{ redeeming ? '核销中…' : '兑换' }}
          </button>
        </form>
        <p v-if="redeemMsg" class="ok-box" role="status">{{ redeemMsg }}</p>
        <p v-if="redeemErr" class="error-box" role="alert">{{ redeemErr }}</p>
      </div>

      <div class="card">
        <h3>积分流水</h3>
        <p v-if="ledger.length === 0" class="hint" role="status">
          无积分流水。完成首次充值或使用试用额度后这里会显示明细。
        </p>
        <table v-else class="list">
          <thead>
            <tr><th>时间</th><th>类型</th><th>变动</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="e in ledger" :key="e.ledger_id">
              <td>{{ new Date(e.created_at).toLocaleString() }}</td>
              <td>{{ LEDGER_LABEL[e.ledger_type] ?? e.ledger_type }}</td>
              <td :class="e.points_change < 0 ? 'neg' : 'pos'">
                {{ e.points_change > 0 ? '+' : '' }}{{ e.points_change }}
              </td>
              <td class="hint">{{ e.description ?? '' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.cards-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.stat-num { font-size: 26px; font-weight: 700; margin: 4px 0; }
.stat-label { color: var(--fg-soft); font-size: 13px; margin: 0; }
.redeem-row { display: flex; gap: 12px; align-items: center; }
.sr-only {
  position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap;
}
.neg { color: var(--err); font-weight: 600; }
.pos { color: var(--ok); font-weight: 600; }
@media (max-width: 860px) { .cards-row { grid-template-columns: 1fr; } }
</style>
