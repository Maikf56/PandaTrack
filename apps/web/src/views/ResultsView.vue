<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { api, type TrackingView, type CheckUpdateResult } from '../api/client'
import { loadStatusDict, session, statusLabel } from '../composables/session'
import { useSse, visibilityPolling, createChangeTracker } from '../composables/sse'

// 结果列表（04 §5.6/§8.2，G2 流程 3）：筛选 + 检查更新防呆 + 变化感知。
const items = ref<TrackingView[]>([])
const loading = ref(true)
const error = ref('')
const search = ref('')
const filterStatus = ref('')
const selected = ref<Set<string>>(new Set())
const checkFeedback = ref('')

// 检查更新弹层（§5.6：默认勾选异常与暂未获取项；实时显示沿用计数）
const checkDialogOpen = ref(false)
const checkChecked = ref<Set<string>>(new Set())
const checking = ref(false)

// 变化感知（§8.2）：刷新后对状态跃迁行 1.2s 高亮淡出 + 摘要条
const tracker = createChangeTracker()
const changeSummary = ref(0)
const stopPolling = visibilityPolling(reload, 15000)

// 实时通道（§8.2）：SSE 推送 → 800ms 防抖自动刷新；轮询为断线兜底
// （结果页是等待场景，自动更新优于手动提示；SSE 在线时轮询自动跳过）
const { hasUpdate, open, close } = useSse()
let reloadTimer: ReturnType<typeof setTimeout> | null = null
watch(hasUpdate, (v) => {
  if (!v) return
  if (reloadTimer) clearTimeout(reloadTimer)
  reloadTimer = setTimeout(() => {
    hasUpdate.value = false
    void reload()
  }, 800)
})

onMounted(async () => {
  open()
  await loadStatusDict()
  await reload()
})

onUnmounted(() => {
  stopPolling()
  close()
  if (reloadTimer) clearTimeout(reloadTimer)
})

async function reload() {
  loading.value = items.value.length === 0
  error.value = ''
  try {
    const { data } = await api.get<TrackingView[]>('/api/v1/trackings')
    // 变化感知：以本页快照对比（客户触发式呈现——数据只在刷新时更新）
    const snapshot = new Map(data.map((it) => [it.id, it.status_key]))
    const changed = tracker.feed(snapshot)
    if (changed > 0) changeSummary.value = changed
    items.value = data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

const filtered = computed(() =>
  items.value.filter((it) => {
    if (search.value && !it.normalized_number.includes(search.value.trim())) return false
    if (filterStatus.value && it.status_key !== filterStatus.value) return false
    return true
  }),
)

function toggle(id: string) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

const ANOMALY_KEYS = new Set(['not_found', 'exception', 'delivery_failed', 'returned'])

/** 检查更新弹层：默认勾选异常态 + 非终态暂未获取项（最常见的重查动机）。 */
function openCheckDialog() {
  const pre = new Set<string>()
  for (const it of items.value) {
    if (!selected.value.has(it.id)) continue
    if (ANOMALY_KEYS.has(it.status_key) || !it.is_terminal) pre.add(it.id)
  }
  checkChecked.value = pre
  checkDialogOpen.value = true
}

/** 勾选面板实时计数：终态将自动沿用，不发起查询。 */
const checkSummary = computed(() => {
  let terminal = 0
  for (const it of items.value) {
    if (checkChecked.value.has(it.id) && it.is_terminal) terminal++
  }
  return { total: checkChecked.value.size, terminal }
})

async function submitCheckUpdates() {
  if (checkChecked.value.size === 0 || checking.value) return
  checking.value = true
  checkFeedback.value = ''
  try {
    const { data } = await api.post<CheckUpdateResult[]>('/api/v1/check-updates', {
      customer_tracking_ids: [...checkChecked.value],
    })
    const fresh = data.filter((r) => r.fresh).length
    const willFetch = data.filter((r) => r.will_fetch).length
    checkFeedback.value =
      `已提交检查：${data.length} 项；其中 ${fresh} 项将沿用现有结果，` +
      `${willFetch} 项已创建检查任务。结果在后台更新，稍后查看。`
    checkDialogOpen.value = false
  } catch (e) {
    checkFeedback.value = ''
    error.value = (e as { message: string }).message
  } finally {
    checking.value = false
  }
}

/* 双状态常驻图例（04 §5.13）：任务状态与物流状态两套概念 */
const legendOpen = ref(false)
const itemStateLegend = [
  { key: 'accepted', label: '提交已受理：已收到你的请求，正在安排查询' },
  { key: 'processing', label: '查询中：正在查询，结果会逐步更新' },
  { key: 'done', label: '已获取结果：当前展示的是已取得的结果' },
  { key: 'missing', label: '暂未获取：暂时还没有可展示结果' },
]

function isChanged(id: string) {
  return tracker.changedIds.value.has(id)
}
</script>

<template>
  <section>
    <div class="title-row">
      <div>
        <h1 class="page-title">结果列表</h1>
        <p class="page-sub">按状态、单号筛选你的查询结果；结果由服务端按当前身份过滤。</p>
      </div>
      <div class="legend-wrap">
        <button class="btn ghost sm" aria-label="状态图例" @click="legendOpen = !legendOpen">ⓘ 状态图例</button>
        <div v-if="legendOpen" class="legend-card">
          <h4>任务状态（系统查完没有）</h4>
          <ul>
            <li v-for="l in itemStateLegend" :key="l.key">{{ l.label }}</li>
          </ul>
          <h4>物流状态（包裹走到哪）</h4>
          <p class="hint">两套状态相互独立：「查询失败」和「投递失败」不是一回事。</p>
          <div class="legend-badges">
            <span v-for="s in session.statusDict?.statuses ?? []" :key="s.key" class="badge">
              {{ s.label_zh }}{{ s.terminal ? ' · 终态' : '' }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <div class="card filters">
      <label for="fl-search">单号搜索</label>
      <input id="fl-search" v-model="search" placeholder="输入单号片段" />
      <label for="fl-status">状态</label>
      <select id="fl-status" v-model="filterStatus">
        <option value="">全部状态</option>
        <option v-for="s in session.statusDict?.statuses ?? []" :key="s.key" :value="s.key">
          {{ s.label_zh }}{{ s.terminal ? '（终态）' : '' }}
        </option>
      </select>
    </div>

    <!-- 变更摘要条（04 §8.2）：翻页不打断更新流，一键跳到已变更 -->
    <div v-if="changeSummary > 0" class="card change-bar" role="status">
      <strong>{{ changeSummary }}</strong> 个状态更新 — 列表中高亮显示（1.2 秒后淡出）
      <button class="btn ghost sm" @click="changeSummary = 0; tracker.clear()">知道了</button>
    </div>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>
    <div v-else-if="filtered.length === 0" class="card empty-state" role="status">
      <p>还没有查询记录。先粘贴 USPS 单号开始查询，提交后这里会显示结果。</p>
      <RouterLink class="btn" to="/submit">去提交第一批单号</RouterLink>
    </div>

    <table v-else class="list">
      <thead>
        <tr>
          <th>选择</th>
          <th>单号</th>
          <th>当前状态</th>
          <th>取得时间</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="it in filtered" :key="it.id" :class="{ flash: isChanged(it.id) }">
          <td>
            <input
              type="checkbox"
              :checked="selected.has(it.id)"
              :aria-label="`选择 ${it.normalized_number}`"
              @change="toggle(it.id)"
            />
          </td>
          <td class="mono">{{ it.normalized_number }}</td>
          <td>
            <span class="badge" :class="{ terminal: it.is_terminal }">{{ it.label_zh || statusLabel(it.status_key) }}</span>
          </td>
          <td>{{ it.last_success_at ? new Date(it.last_success_at).toLocaleString() : '暂未获取' }}</td>
          <td>
            <RouterLink :to="`/results/${it.id}`">查看详情</RouterLink>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="card bulk" v-if="selected.size > 0">
      <p class="hint">已选择 {{ selected.size }} 项</p>
      <p v-if="checkFeedback" class="ok-box" role="status">{{ checkFeedback }}</p>
      <button class="btn" :disabled="checking" @click="openCheckDialog">
        {{ checking ? '提交检查中…' : '检查更新' }}
      </button>
    </div>

    <!-- 检查更新弹层（04 §5.6）：默认勾选异常态，实时显示沿用计数 -->
    <div v-if="checkDialogOpen" class="modal-mask" @click.self="checkDialogOpen = false">
      <div class="modal card" role="dialog" aria-modal="true" aria-label="检查更新">
        <h3>检查更新</h3>
        <p class="hint">已默认勾选异常与暂未获取项——最常见的重查动机不需要每次手点；勾选可修改。</p>
        <div class="check-list">
          <label v-for="it in items.filter((x) => selected.has(x.id))" :key="it.id" class="check-row">
            <input
              v-model="checkChecked"
              type="checkbox"
              :value="it.id"
            />
            <span class="mono">{{ it.normalized_number }}</span>
            <span class="badge" :class="{ terminal: it.is_terminal }">{{ it.label_zh || statusLabel(it.status_key) }}</span>
          </label>
        </div>
        <p class="ok-box" role="status">
          将检查 <strong class="mono">{{ checkSummary.total }}</strong> 条 · 不扣积分 ·
          其中终态 <strong class="mono">{{ checkSummary.terminal }}</strong> 条将自动沿用现有结果（不发起查询）
        </p>
        <div class="actions">
          <button class="btn" :disabled="checkSummary.total === 0 || checking" @click="submitCheckUpdates">
            {{ checking ? '提交检查中…' : '提交检查' }}
          </button>
          <button class="btn ghost" @click="checkDialogOpen = false">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.title-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.legend-wrap { position: relative; }
.legend-card {
  position: absolute; right: 0; top: 40px; width: 340px; z-index: 20;
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-panel);
  box-shadow: var(--shadow-2); padding: 16px; font-size: 13px;
}
.legend-card h4 { margin: 8px 0 4px; font-size: 13px; }
.legend-card ul { margin: 0; padding-left: 16px; color: var(--fg-soft); }
.legend-badges { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.filters { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }
.filters label { display: block; font-size: 13px; color: var(--fg-soft); margin-bottom: 4px; }
.filters input, .filters select { width: auto; min-width: 180px; }
.change-bar { display: flex; align-items: center; gap: 12px; border-left: 3px solid var(--brand); }
.bulk { border-left: 3px solid var(--brand); }
.check-list { max-height: 280px; overflow-y: auto; margin: 10px 0; }
.check-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--line); font-size: 14px; }
.check-row input { width: auto; }
.check-row .mono { flex: 1; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(28, 25, 23, 0.4);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal { width: min(520px, 92vw); margin: 0; box-shadow: var(--shadow-2); }
.actions { display: flex; gap: 12px; margin-top: 12px; }
</style>
