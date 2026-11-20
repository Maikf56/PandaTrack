<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { api, type TrackingView, type CheckUpdateResult, type TrackingEvent } from '../api/client'
import { loadStatusDict, session, statusLabel } from '../composables/session'
import { useSse, visibilityPolling, createChangeTracker } from '../composables/sse'

// 结果列表（04 §5.6/§8.2，G2 流程 3；P14 分组视图重构）：
// 批次/分组/平铺三种视图 + 深链 ?op=/?group= + 快捷筛选 + 行内最新事件。
const items = ref<TrackingView[]>([])
const loading = ref(true)
const error = ref('')
const search = ref('')
const filterStatus = ref('')
const selected = ref<Set<string>>(new Set())
const checkFeedback = ref('')

// 深链：提交记录/分组页跳转进来直接落在对应批次/分组（修复 /results?op= 断链）
const route = useRoute()
const opFilter = ref<string | null>(null)
const groupFilter = ref<string | null>(null)

// 视图模式：批次（默认，按"最近提交"组织）/ 分组 / 平铺
const viewMode = ref<'batch' | 'group' | 'flat'>('batch')

// 快捷筛选：待跟进（非终态）与异常是最常用的两个口径
const quickFilter = ref<'all' | 'pending' | 'anomaly'>('all')

// 折叠的批次/分组（按 key）
const collapsed = ref<Set<string>>(new Set())

// 检查更新弹层（§5.6：默认勾选异常与暂未获取项；实时显示沿用计数）
const checkDialogOpen = ref(false)
const checkChecked = ref<Set<string>>(new Set())
const checking = ref(false)

// 变化感知（§8.2）：刷新后对状态跃迁行 1.2s 高亮淡出 + 摘要条
const tracker = createChangeTracker()
const changeSummary = ref(0)
const stopPolling = visibilityPolling(reload, 15000)

// 实时通道（§8.2）：SSE 推送 → 800ms 防抖自动刷新；轮询为断线兜底
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
  const qOp = route.query.op
  if (typeof qOp === 'string' && qOp) opFilter.value = qOp
  const qGroup = route.query.group
  if (typeof qGroup === 'string' && qGroup) groupFilter.value = qGroup
  if (groupFilter.value) viewMode.value = 'group'
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

const baseFiltered = computed(() =>
  items.value.filter((it) => {
    if (search.value && !it.normalized_number.includes(search.value.trim())) return false
    if (filterStatus.value && it.status_key !== filterStatus.value) return false
    if (quickFilter.value === 'pending' && it.is_terminal) return false
    if (quickFilter.value === 'anomaly' && !ANOMALY_KEYS.has(it.status_key)) return false
    return true
  }),
)

const filtered = computed(() => {
  let arr = baseFiltered.value
  if (opFilter.value) arr = arr.filter((it) => it.batch_id === opFilter.value)
  if (groupFilter.value) arr = arr.filter((it) => it.group_name === groupFilter.value)
  return arr
})

/* 快捷筛选计数（待跟进/异常） */
const quickCounts = computed(() => ({
  pending: items.value.filter((it) => !it.is_terminal).length,
  anomaly: items.value.filter((it) => ANOMALY_KEYS.has(it.status_key)).length,
}))

const ANOMALY_KEYS = new Set(['not_found', 'exception', 'delivery_failed', 'returned'])

/* 分组视图的段（批次 / 分组 / 平铺统一结构） */
interface Section {
  key: string
  title: string
  time: string | null
  items: TrackingView[]
  terminalCount: number
}

function fmtSectionTime(t?: string | null): string {
  if (!t) return ''
  const d = new Date(t)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const sections = computed<Section[]>(() => {
  if (viewMode.value === 'flat') {
    return [{ key: 'all', title: '全部记录', time: null,
              items: filtered.value,
              terminalCount: filtered.value.filter((it) => it.is_terminal).length }]
  }
  const map = new Map<string, Section>()
  for (const it of filtered.value) {
    let key: string, title: string, time: string | null
    if (viewMode.value === 'batch') {
      key = it.batch_id || 'none'
      time = it.batch_created_at || null
      title = time ? `提交于 ${fmtSectionTime(time)}` : '更早的单号（未关联提交批次）'
    } else {
      key = it.group_name || '__ungrouped'
      time = null
      title = it.group_name || '未分组'
    }
    let sec = map.get(key)
    if (!sec) {
      sec = { key, title, time, items: [], terminalCount: 0 }
      map.set(key, sec)
    }
    sec.items.push(it)
    if (it.is_terminal) sec.terminalCount++
  }
  const list = [...map.values()]
  if (viewMode.value === 'batch') {
    // 批次按提交时间倒序；未关联批次的沉底
    list.sort((a, b) => (b.time ?? '').localeCompare(a.time ?? ''))
    const noneIdx = list.findIndex((s) => s.key === 'none')
    if (noneIdx >= 0) list.push(list.splice(noneIdx, 1)[0])
  }
  return list
})

function toggleCollapse(key: string) {
  const next = new Set(collapsed.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsed.value = next
}

function selectSection(sec: Section) {
  const next = new Set(selected.value)
  for (const it of sec.items) next.add(it.id)
  selected.value = next
}

function clearDeepLink() {
  opFilter.value = null
  groupFilter.value = null
}

function clearAllFilters() {
  search.value = ''
  filterStatus.value = ''
  quickFilter.value = 'all'
}

const hasAnyFilter = computed(() =>
  search.value !== '' || filterStatus.value !== '' ||
  quickFilter.value !== 'all' || opFilter.value !== null || groupFilter.value !== null,
)

/* 行内最新事件（events 时间倒序，首条即最新） */
function latestEvent(it: TrackingView): TrackingEvent | undefined {
  return it.events?.[0]
}

function fmtEventTime(t?: string | null): string {
  if (!t) return ''
  return fmtSectionTime(t)
}

function fmtGetTime(t?: string | null): string {
  return t ? new Date(t).toLocaleString() : '暂未获取'
}

function toggle(id: string) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

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
        <p class="page-sub">按提交批次或分组查看查询结果；结果由服务端按当前身份过滤。</p>
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
      <button
        v-if="hasAnyFilter"
        class="btn ghost sm"
        @click="clearDeepLink(); clearAllFilters()"
      >清除全部筛选</button>
    </div>

    <!-- 视图切换 + 快捷筛选 chips（P14） -->
    <div class="view-bar">
      <div class="seg" role="group" aria-label="视图模式">
        <button
          v-for="m in ([
            { v: 'batch', t: '按提交批次' },
            { v: 'group', t: '按分组' },
            { v: 'flat', t: '平铺' },
          ] as const)" :key="m.v"
          class="seg-btn"
          :class="{ active: viewMode === m.v }"
          @click="viewMode = m.v"
        >{{ m.t }}</button>
      </div>
      <div class="chips">
        <button
          class="chip" :class="{ active: quickFilter === 'all' }"
          @click="quickFilter = 'all'"
        >全部</button>
        <button
          class="chip" :class="{ active: quickFilter === 'pending' }"
          @click="quickFilter = quickFilter === 'pending' ? 'all' : 'pending'"
        >待跟进 <span class="chip-n">{{ quickCounts.pending }}</span></button>
        <button
          class="chip" :class="{ active: quickFilter === 'anomaly' }"
          @click="quickFilter = quickFilter === 'anomaly' ? 'all' : 'anomaly'"
        >异常 <span class="chip-n">{{ quickCounts.anomaly }}</span></button>
        <button class="chip" @click="selectSection(sections[0])" v-if="sections.length > 0">全选当前结果</button>
      </div>
    </div>

    <!-- 深链提示条：从提交记录/分组页跳入时说明当前范围 -->
    <div v-if="opFilter || groupFilter" class="card change-bar" role="status">
      正在查看{{ opFilter ? '某一次提交批次' : `「${groupFilter}」分组` }}的结果
      <button class="btn ghost sm" @click="clearDeepLink">查看全部</button>
    </div>

    <!-- 变更摘要条（04 §8.2）：翻页不打断更新流，一键跳到已变更 -->
    <div v-if="changeSummary > 0" class="card change-bar" role="status">
      <strong>{{ changeSummary }}</strong> 个状态更新 — 列表中高亮显示（1.2 秒后淡出）
      <button class="btn ghost sm" @click="changeSummary = 0; tracker.clear()">知道了</button>
    </div>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>
    <div v-else-if="items.length === 0" class="card empty-state" role="status">
      <p>还没有查询记录。先粘贴 USPS 单号开始查询，提交后这里会显示结果。</p>
      <RouterLink class="btn" to="/submit">去提交第一批单号</RouterLink>
    </div>
    <div v-else-if="filtered.length === 0" class="card empty-state" role="status">
      <p>没有符合当前筛选条件的记录。</p>
      <button class="btn ghost" @click="clearDeepLink(); clearAllFilters()">清除筛选</button>
    </div>

    <div v-else class="sections">
      <div v-for="sec in sections" :key="sec.key" class="sec">
        <!-- 段头：批次显示时间与完结进度；平铺不显示头 -->
        <button
          v-if="viewMode !== 'flat'"
          class="sec-head"
          :aria-expanded="!collapsed.has(sec.key)"
          @click="toggleCollapse(sec.key)"
        >
          <span class="sec-caret" :class="{ open: !collapsed.has(sec.key) }">▸</span>
          <span class="sec-title">{{ sec.title }}</span>
          <span class="sec-meta">
            共 {{ sec.items.length }} 条 · 已完结 {{ sec.terminalCount }} 条
          </span>
          <span
            class="sec-select"
            role="button"
            tabindex="0"
            @click.stop="selectSection(sec)"
            @keydown.enter.prevent="selectSection(sec)"
          >选本组</span>
        </button>
        <div v-if="viewMode === 'flat' || !collapsed.has(sec.key)" class="sec-body">
          <div
            v-for="it in sec.items"
            :key="it.id"
            class="row"
            :class="{ flash: isChanged(it.id) }"
          >
            <input
              type="checkbox"
              class="row-check"
              :checked="selected.has(it.id)"
              :aria-label="`选择 ${it.normalized_number}`"
              @change="toggle(it.id)"
            />
            <div class="row-main">
              <div class="row-top">
                <span class="mono num">{{ it.normalized_number }}</span>
                <span class="badge" :class="{ terminal: it.is_terminal }">
                  {{ it.label_zh || statusLabel(it.status_key) }}
                </span>
              </div>
              <div v-if="latestEvent(it)" class="row-sub">
                <span class="evt">{{ latestEvent(it)!.description || latestEvent(it)!.label_zh }}</span>
                <span v-if="fmtEventTime(latestEvent(it)!.occurred_at)" class="evt-time">
                  {{ fmtEventTime(latestEvent(it)!.occurred_at) }}
                </span>
              </div>
              <div v-else class="row-sub"><span class="evt dim">暂无轨迹事件</span></div>
            </div>
            <div class="row-side">
              <span class="get-time">{{ fmtGetTime(it.last_success_at) }}</span>
              <RouterLink :to="`/results/${it.id}`">详情</RouterLink>
            </div>
          </div>
        </div>
      </div>
    </div>

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

/* 视图切换 + 快捷筛选 */
.view-bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 12px; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.seg-btn {
  border: 0; background: transparent; padding: 6px 14px; font-size: 13px;
  color: var(--fg-soft); cursor: pointer;
}
.seg-btn + .seg-btn { border-left: 1px solid var(--line); }
.seg-btn.active { background: var(--brand); color: #fff; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip {
  border: 1px solid var(--line); border-radius: 999px; background: transparent;
  padding: 4px 12px; font-size: 13px; color: var(--fg-soft); cursor: pointer;
}
.chip.active { border-color: var(--brand); color: var(--brand); font-weight: 600; }
.chip-n {
  display: inline-block; min-width: 18px; text-align: center; margin-left: 2px;
  background: var(--line); border-radius: 999px; font-size: 12px; padding: 0 5px;
}
.change-bar { display: flex; align-items: center; gap: 12px; border-left: 3px solid var(--brand); }

/* 分组段 */
.sections { margin-top: 12px; display: flex; flex-direction: column; gap: 12px; }
.sec { border: 1px solid var(--line); border-radius: var(--radius-panel); background: var(--panel); overflow: hidden; }
.sec-head {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 10px 14px; border: 0; background: transparent; cursor: pointer;
  font-size: 14px; text-align: left;
}
.sec-caret { display: inline-block; transition: transform 120ms ease-out; color: var(--fg-soft); }
.sec-caret.open { transform: rotate(90deg); }
.sec-title { font-weight: 600; }
.sec-meta { color: var(--fg-soft); font-size: 13px; }
.sec-select {
  margin-left: auto; font-size: 13px; color: var(--brand);
  border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; cursor: pointer;
}
.sec-body { border-top: 1px solid var(--line); }

/* 行 */
.row {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px; border-bottom: 1px solid var(--line);
}
.sec-body .row:last-child { border-bottom: 0; }
.row-check { width: auto; flex: none; }
.row-main { flex: 1; min-width: 0; }
.row-top { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.row-top .num { font-size: 14px; }
.row-sub { display: flex; gap: 10px; align-items: baseline; margin-top: 2px; min-width: 0; }
.evt {
  color: var(--fg-soft); font-size: 13px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 52ch;
}
.evt.dim { font-style: italic; }
.evt-time { color: var(--fg-soft); font-size: 12px; flex: none; }
.row-side { flex: none; display: flex; align-items: center; gap: 14px; }
.get-time { color: var(--fg-soft); font-size: 12px; }

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

@media (max-width: 640px) {
  .row { flex-wrap: wrap; }
  .row-side { width: 100%; justify-content: space-between; }
  .sec-select { flex: none; }
}
</style>
