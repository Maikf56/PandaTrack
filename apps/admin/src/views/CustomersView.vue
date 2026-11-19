<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, can, type CustomerRow, type LedgerRow, type AuditRow } from '../api/client'

// 客户管理（03 §3.2）：以客户为中心——点行展开详情抽屉（资料/余额/流水/审计聚合），
// 高风险操作（调整积分/冻结/恢复）从抽屉发起，客户 ID 自动携带，不再手输。
// RBAC：customers:write 控操作按钮、billing:read 控流水区（后端权威校验）。
const canWrite = can('customers:write')
const canReadBilling = can('billing:read')
const canReadAudit = can('audit:read')

const items = ref<CustomerRow[]>([])
const total = ref(0)
const loading = ref(true)
const error = ref('')
const feedback = ref('')
const search = ref('')
const statusFilter = ref('')

// ---- 详情抽屉 ----
const drawerCustomer = ref<CustomerRow | null>(null)
const drawerLedger = ref<LedgerRow[]>([])
const drawerAudit = ref<AuditRow[]>([])
const drawerLoading = ref(false)

// ---- 高风险操作（状态变更 / 积分调整共用确认弹窗）----
const statusTarget = ref<CustomerRow | null>(null)
const nextStatus = ref<'active' | 'suspended' | 'deleted'>('suspended')
const reason = ref('')
const submittingStatus = ref(false)

const adjustOpen = ref(false)
const adjustDelta = ref<number | null>(null)
const adjustDesc = ref('')
const adjustSubmitting = ref(false)

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
    // 抽屉打开中：同步刷新其数据，保证状态/余额为最新
    if (drawerCustomer.value) {
      const fresh = data.items.find(
        (c) => c.customer_id === drawerCustomer.value!.customer_id)
      if (fresh) drawerCustomer.value = fresh
      else closeDrawer()
    }
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

const filtered = computed(() =>
  items.value.filter((row) => {
    if (statusFilter.value && row.status !== statusFilter.value) return false
    const q = search.value.trim().toLowerCase()
    if (!q) return true
    return row.email.toLowerCase().includes(q) || row.public_id.toLowerCase().includes(q)
  }),
)

// ---- 抽屉聚合加载 ----
async function openDrawer(row: CustomerRow) {
  drawerCustomer.value = row
  drawerLedger.value = []
  drawerAudit.value = []
  const jobs: Promise<unknown>[] = []
  if (canReadBilling) {
    jobs.push(api.get<{ items: LedgerRow[] }>('/api/v1/admin/billing/ledger', {
      customer_id: row.customer_id, limit: 10,
    }).then((d) => { drawerLedger.value = d.items }))
  }
  if (canReadAudit) {
    jobs.push(api.get<{ items: AuditRow[] }>('/api/v1/admin/audit', {
      target: String(row.customer_id), limit: 10,
    }).then((d) => { drawerAudit.value = d.items }))
  }
  drawerLoading.value = true
  try {
    await Promise.all(jobs)
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    drawerLoading.value = false
  }
}

function closeDrawer() {
  drawerCustomer.value = null
  drawerLedger.value = []
  drawerAudit.value = []
}

// ---- 状态变更（冻结/恢复，理由必填 + 审计）----
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
    feedback.value = `客户 ${statusTarget.value.email} 已置为 ${statusLabelZh[nextStatus.value]}`
    statusTarget.value = null
    await reload()
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    submittingStatus.value = false
  }
}

// ---- 积分调整（从抽屉发起；billing:write 由后端校验）----
function openAdjust() {
  adjustDelta.value = null
  adjustDesc.value = ''
  adjustOpen.value = true
}

async function submitAdjust() {
  const cust = drawerCustomer.value
  if (!cust) return
  if (!adjustDelta.value || adjustDelta.value === 0) {
    error.value = '调整幅度不能为 0'
    return
  }
  if (!adjustDesc.value.trim()) {
    error.value = '必须填写调整说明'
    return
  }
  adjustSubmitting.value = true
  error.value = ''
  try {
    await api.post('/api/v1/admin/billing/adjust', undefined, {
      customer_id: cust.customer_id,
      delta: adjustDelta.value,
      description: adjustDesc.value.trim(),
      reason: '客户详情抽屉操作',
    })
    feedback.value = `客户 ${cust.email} 积分调整已入账并写入审计`
    adjustOpen.value = false
    await reload()
    await openDrawer(drawerCustomer.value ?? cust)
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    adjustSubmitting.value = false
  }
}

const statusBadgeClass: Record<string, string> = {
  active: 'ok', suspended: 'warn', deleted: 'err',
}
const statusLabelZh: Record<string, string> = {
  active: '正常', suspended: '已冻结', deleted: '已删除',
}
const ledgerTypeZh: Record<string, string> = {
  charge: '提交扣费', topup: '充值', bonus: '赠送', adjust: '人工调整', reversal: '冲正/退款',
}
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
    <h1 class="page-title">客户管理</h1>
    <p class="page-sub">
      共 {{ total }} 个客户；点击行展开详情（余额/流水/审计），冻结与积分调整均在详情内发起。
    </p>

    <div class="card form-row">
      <div>
        <label for="cust-search" class="field-label">搜索客户</label>
        <input id="cust-search" v-model="search" placeholder="邮箱或客户 ID 片段" />
      </div>
      <div style="max-width: 180px">
        <label for="cust-status" class="field-label">状态</label>
        <select id="cust-status" v-model="statusFilter">
          <option value="">全部</option>
          <option value="active">正常</option>
          <option value="suspended">已冻结</option>
          <option value="deleted">已删除</option>
        </select>
      </div>
    </div>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="feedback" class="ok-box" role="status">{{ feedback }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <table v-else-if="filtered.length" class="list clickable">
      <thead>
        <tr>
          <th>邮箱</th>
          <th>余额</th>
          <th>状态</th>
          <th>租户</th>
          <th>注册时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in filtered" :key="row.customer_id" tabindex="0"
            @click="openDrawer(row)" @keydown.enter="openDrawer(row)">
          <td>
            {{ row.email }}
            <span v-if="row.status === 'active'" class="row-open hint">详情 →</span>
          </td>
          <td class="mono">{{ row.balance ?? 0 }} 积分</td>
          <td>
            <span class="badge" :class="statusBadgeClass[row.status] ?? ''">
              {{ statusLabelZh[row.status] ?? row.status }}
            </span>
          </td>
          <td class="mono">{{ row.tenant_id ?? '—' }}</td>
          <td>{{ fmtTime(row.created_at) }}</td>
        </tr>
      </tbody>
    </table>
    <div v-else class="card"><p class="hint" role="status">没有匹配的客户。</p></div>

    <!-- 客户详情抽屉：以客户为中心的聚合视图 -->
    <div v-if="drawerCustomer" class="drawer-mask" @click.self="closeDrawer">
      <aside class="drawer" role="dialog" aria-modal="true" aria-label="客户详情">
        <div class="drawer-head">
          <div>
            <h3>{{ drawerCustomer.email }}</h3>
            <p class="hint">
              ID <span class="mono">{{ drawerCustomer.customer_id }}</span> ·
              注册于 {{ fmtTime(drawerCustomer.created_at) }}
            </p>
          </div>
          <button class="btn ghost sm" @click="closeDrawer">关闭</button>
        </div>

        <div class="drawer-stat">
          <div>
            <p class="stat-label">钱包余额</p>
            <p class="stat-value">{{ drawerCustomer.balance ?? 0 }}<span class="stat-unit">积分</span></p>
          </div>
          <div>
            <p class="stat-label">状态</p>
            <p>
              <span class="badge" :class="statusBadgeClass[drawerCustomer.status] ?? ''">
                {{ statusLabelZh[drawerCustomer.status] ?? drawerCustomer.status }}
              </span>
            </p>
          </div>
        </div>

        <div v-if="canWrite" class="drawer-actions">
          <button class="btn sm" @click="openAdjust">调整积分</button>
          <button v-if="drawerCustomer.status === 'active'"
                  class="btn ghost sm" @click="openStatusDialog(drawerCustomer, 'suspended')">
            冻结客户
          </button>
          <button v-else-if="drawerCustomer.status === 'suspended'"
                  class="btn ghost sm" @click="openStatusDialog(drawerCustomer, 'active')">
            恢复客户
          </button>
        </div>

        <div v-if="drawerLoading" class="hint" role="status">正在加载流水与审计…</div>

        <template v-else>
          <section v-if="canReadBilling">
            <h4>最近流水</h4>
            <p v-if="!drawerLedger.length" class="hint">暂无流水记录。</p>
            <table v-else class="list">
              <thead><tr><th>类型</th><th>变动</th><th>说明</th><th>时间</th></tr></thead>
              <tbody>
                <tr v-for="r in drawerLedger" :key="r.ledger_id">
                  <td>{{ ledgerTypeZh[r.ledger_type] ?? r.ledger_type }}</td>
                  <td class="mono" :style="{ color: r.points_change > 0 ? 'var(--ok)' : 'var(--err)' }">
                    {{ r.points_change > 0 ? '+' : '' }}{{ r.points_change }}
                  </td>
                  <td>{{ r.description ?? '—' }}</td>
                  <td>{{ fmtTime(r.created_at) }}</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section v-if="canReadAudit">
            <h4>该客户相关审计</h4>
            <p v-if="!drawerAudit.length" class="hint">暂无针对该客户的管理操作记录。</p>
            <ul v-else class="audit-mini">
              <li v-for="a in drawerAudit" :key="a.audit_id">
                <span class="badge">{{ AUDIT_ACTION_ZH[a.action] ?? a.action }}</span>
                <span class="hint">{{ fmtTime(a.created_at) }}</span>
              </li>
            </ul>
          </section>
        </template>
      </aside>
    </div>

    <!-- 状态变更确认（03 §3.1：记录操作者、对象、理由、前后状态） -->
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

    <!-- 积分调整确认（追加流水 + 审计，不改余额绝对值） -->
    <div v-if="adjustOpen" class="modal-mask" @click.self="adjustOpen = false">
      <div class="modal card" role="dialog" aria-modal="true" aria-label="积分调整确认">
        <h3>确认积分调整</h3>
        <ul class="kv">
          <li><span>客户</span><span class="mono">{{ drawerCustomer?.email }}</span></li>
          <li><span>当前余额</span><span class="mono">{{ drawerCustomer?.balance ?? 0 }} 积分</span></li>
        </ul>
        <div class="form-row">
          <div>
            <label for="adj-delta" class="field-label">调整幅度（正加负减）</label>
            <input id="adj-delta" v-model.number="adjustDelta" type="number" class="mono" placeholder="例如 100 或 -50" />
          </div>
          <div>
            <label for="adj-desc" class="field-label">调整说明</label>
            <input id="adj-desc" v-model="adjustDesc" placeholder="例如：故障补偿" />
          </div>
        </div>
        <div class="actions">
          <button class="btn" :class="{ danger: (adjustDelta ?? 0) < 0 }" :disabled="adjustSubmitting" @click="submitAdjust">
            {{ adjustSubmitting ? '提交中…' : '确认调整' }}
          </button>
          <button class="btn ghost" @click="adjustOpen = false">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.actions { display: flex; gap: 12px; margin-top: 12px; }
table.clickable tbody tr { cursor: pointer; }
.row-open { margin-left: 8px; font-size: 12px; }

.drawer-mask {
  position: fixed; inset: 0; background: rgba(28, 25, 23, 0.4); z-index: 40;
  display: flex; justify-content: flex-end;
}
.drawer {
  width: min(480px, 94vw); height: 100dvh; overflow-y: auto;
  background: var(--panel); padding: 24px 22px 40px;
  box-shadow: var(--shadow-2);
  animation: drawer-in 180ms ease-out;
}
@keyframes drawer-in {
  from { transform: translateX(24px); opacity: 0; }
  to { transform: none; opacity: 1; }
}
.drawer-head { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
.drawer-head h3 { margin: 0 0 4px; }
.drawer-stat {
  display: flex; gap: 28px; padding: 14px 0; margin: 14px 0;
  border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
}
.drawer-stat .stat-label { color: var(--fg-soft); font-size: 13px; margin: 0 0 4px; }
.drawer-stat .stat-value { font-size: 26px; font-weight: 700; margin: 0; }
.stat-unit { font-size: 13px; font-weight: 500; color: var(--fg-soft); margin-left: 4px; }
.drawer-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; }
.drawer h4 { margin: 18px 0 8px; font-size: 15px; }
.audit-mini { list-style: none; margin: 0; padding: 0; }
.audit-mini li {
  display: flex; gap: 12px; align-items: baseline; padding: 7px 0;
  border-bottom: 1px dashed var(--line);
}
.audit-mini li:last-child { border-bottom: none; }
</style>
