<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type BatchView, type TrackingView, type CheckUpdateResult } from '../api/client'
import { loadStatusDict, session } from '../composables/session'
import { t } from '../i18n'
import { hasUpdate, visibilityPolling, createChangeTracker } from '../composables/sse'
import StatusDistBar from '../components/StatusDistBar.vue'
import TrackingCard from '../components/TrackingCard.vue'

// 结果列表 · 第三级（P15）：批次内单号卡片，展开即看完整轨迹；
// SSE 推送自动刷新 + 状态跃迁高亮；支持旧深链 /results?op=。
const route = useRoute()
const batchId = computed(() => String(route.params.id))

const batch = ref<BatchView | null>(null)
const items = ref<TrackingView[]>([])
const loading = ref(true)
const error = ref('')
const search = ref('')
const filterStatus = ref('')

const tracker = createChangeTracker()
const stopPolling = visibilityPolling(reload, 15000)
let reloadTimer: ReturnType<typeof setTimeout> | null = null
watch(hasUpdate, (v) => {
  if (!v) return
  if (reloadTimer) clearTimeout(reloadTimer)
  reloadTimer = setTimeout(() => { hasUpdate.value = false; void reload() }, 800)
})

onMounted(async () => {
  await Promise.all([loadStatusDict(), reload()])
})
onUnmounted(() => { stopPolling(); if (reloadTimer) clearTimeout(reloadTimer) })

watch(batchId, () => { void reload() })

async function reload() {
  loading.value = items.value.length === 0
  error.value = ''
  try {
    const [bs, ts] = await Promise.all([
      api.get<BatchView[]>('/api/v1/batches', { limit: 100 }),
      // P17：原文直出（事件含英文原文+词典中文），翻译由卡片本地切换
      api.get<TrackingView[]>('/api/v1/trackings'),
    ])
    batch.value = bs.data.find((b) => b.id === batchId.value) ?? null
    // batch_id = 提交操作 public_id（list_trackings LATERAL 最近一次提交）。
    // 单号在多个批次出现时归入最近一次；页面注明口径。
    items.value = ts.data.filter((it) => it.batch_id === batchId.value)
    const snapshot = new Map(ts.data.map((it) => [it.id, it.status_key]))
    tracker.feed(snapshot)
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

// P17 分页器（竞品式）：筛选后分页展示，页码/跳页
const PAGE_SIZE = 20
const page = ref(1)
const pageInput = ref('')
const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const paged = computed(() =>
  filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))
watch([search, filterStatus, batchId], () => { page.value = 1 })
function gotoPage(p: number) {
  page.value = Math.min(Math.max(1, p), totalPages.value)
}

const dist = computed(() => {
  const d: Record<string, number> = {}
  for (const it of items.value) {
    const k = it.status_key || 'other'
    d[k] = (d[k] ?? 0) + 1
  }
  return d
})

const terminalCount = computed(() => items.value.filter((it) => it.is_terminal).length)
/** 批次查询进度（P18）：未完结 →「正在查询中…」，全部终态 →「上一轮查询结束」。 */
const batchRunning = computed(() => items.value.length > 0 && terminalCount.value < items.value.length)

function fmtTime(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 批量检查更新：默认提交全部非终态项（最常见的重查动机），不扣积分。 */
const checking = ref(false)
const checkFeedback = ref('')
async function checkPending() {
  if (checking.value) return
  const ids = items.value.filter((it) => !it.is_terminal).map((it) => it.id)
  if (ids.length === 0) {
    checkFeedback.value = t('gb.all_done')
    return
  }
  checking.value = true
  try {
    const { data } = await api.post<CheckUpdateResult[]>('/api/v1/check-updates', {
      customer_tracking_ids: ids,
    })
    const fresh = data.filter((r) => r.fresh).length
    checkFeedback.value = t('gb.check_done', { n: data.length, fresh })
  } catch (e) {
    checkFeedback.value = ''
    error.value = (e as { message: string }).message
  } finally {
    checking.value = false
  }
}

const exporting = ref(false)
async function exportBatch() {
  if (exporting.value) return
  exporting.value = true
  try {
    await api.post('/api/v1/exports', { scope: 'batch', scope_ref: batchId.value })
    checkFeedback.value = t('gb.export_done')
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <section>
    <p class="crumb"><RouterLink to="/results">{{ t('nav.results') }}</RouterLink> › {{ t('bt.crumb_batch') }}</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">{{ t('common.loading') }}</p>

    <template v-else>
      <div class="card bhead">
        <div class="bhead-row">
          <div>
            <h1 class="page-title">{{ t('bt.title', { time: fmtTime(batch?.created_at) }) }}</h1>
            <p class="hint">
              {{ t('bt.summary', { n: items.length, done: terminalCount, time: fmtTime(batch?.updated_at) }) }}
              <template v-if="batch">{{ t('bt.charged', { n: batch.points_charged }) }}</template>
            </p>
          </div>
          <div class="actions">
            <button class="btn ghost sm" :disabled="checking" @click="checkPending">
              {{ checking ? t('card.checking') : t('bt.recheck_open') }}
            </button>
            <button class="btn ghost sm" :disabled="exporting" @click="exportBatch">{{ t('common.export') }}</button>
          </div>
        </div>
        <StatusDistBar :distribution="dist" :total="items.length" />
        <p v-if="items.length > 0" class="run-state" :class="{ running: batchRunning }" role="status">
          <span class="run-dot"></span>
          <template v-if="batchRunning">
            {{ t('bt.in_progress', { left: items.length - terminalCount, total: items.length }) }}
          </template>
          <template v-else>{{ t('bt.round_done') }}</template>
        </p>
        <p v-if="checkFeedback" class="ok-box" role="status">{{ checkFeedback }}</p>
      </div>

      <div class="card filters">
        <input v-model="search" :placeholder="t('bt.search_placeholder')" :aria-label="t('bt.search_aria')" />
        <select v-model="filterStatus" :aria-label="t('bt.status_aria')">
          <option value="">{{ t('bt.all_status') }}</option>
          <option v-for="s in session.statusDict?.statuses ?? []" :key="s.key" :value="s.key">
            {{ s.label_zh }}
          </option>
        </select>
      </div>

      <div v-if="items.length === 0" class="card empty-state" role="status">
        <p>{{ t('bt.empty') }}</p>
        <button class="btn ghost" @click="reload">{{ t('dash.sse_refresh') }}</button>
      </div>
      <div v-else-if="filtered.length === 0" class="card empty-state" role="status">
        <p>{{ t('bt.no_match') }}</p>
        <button class="btn ghost" @click="search = ''; filterStatus = ''">{{ t('results.clear_filter') }}</button>
      </div>

      <div v-else class="cards">
        <TrackingCard
          v-for="it in paged"
          :key="it.id"
          :item="it"
          :flash="tracker.changedIds.value.has(it.id)"
        />
        <!-- P17 分页器（竞品式） -->
        <div v-if="filtered.length > PAGE_SIZE" class="pager" role="navigation">
          <span class="hint">{{ t('bt.pager_total', { n: filtered.length }) }}</span>
          <label>
            {{ t('bt.pager_per') }}
            <span class="mono">20</span>
          </label>
          <span class="hint">≈</span>
          <button class="pg-btn" :disabled="page <= 1" @click="gotoPage(page - 1)">‹</button>
          <span class="pg-now">{{ page }} / {{ totalPages }}</span>
          <button class="pg-btn" :disabled="page >= totalPages" @click="gotoPage(page + 1)">›</button>
          <span class="hint">{{ t('bt.pager_jump') }}</span>
          <input
            v-model="pageInput"
            class="pg-input mono"
            type="number"
            min="1"
            :max="totalPages"
            @keydown.enter="gotoPage(Number(pageInput) || 1); pageInput = ''"
          />
          <span class="hint">{{ t('bt.pager_page') }}</span>
        </div>
        <p class="hint scope-note">
          {{ t('bt.scope_note') }}
        </p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.crumb { color: var(--fg-soft); font-size: 13px; margin: 0 0 8px; }
.crumb a { color: var(--fg-soft); text-decoration: none; }
.crumb a:hover { color: var(--brand); }
.bhead-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.run-state {
  display: inline-flex; align-items: center; gap: 7px;
  margin: 8px 0 0; font-size: 13px; color: var(--fg-soft);
}
.run-state.running { color: var(--brand-strong); font-weight: 500; }
.run-dot {
  width: 8px; height: 8px; border-radius: 999px; background: var(--fg-soft); flex-shrink: 0;
}
.run-state.running .run-dot {
  background: var(--brand); animation: run-pulse 1.2s ease-in-out infinite;
}
@keyframes run-pulse {
  0%, 100% { box-shadow: 0 0 0 0 var(--brand-line); opacity: 1; }
  50% { box-shadow: 0 0 0 5px var(--brand-soft); opacity: 0.6; }
}
@media (prefers-reduced-motion: reduce) {
  .run-state.running .run-dot { animation: none; }
}
.actions { display: flex; gap: 8px; }
.filters { display: flex; gap: 12px; flex-wrap: wrap; }
.filters input, .filters select { width: auto; min-width: 200px; }
.cards { margin-top: 8px; }
.scope-note { margin-top: 4px; }
.pager {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 14px 4px 4px; border-top: 1px solid var(--line); margin-top: 8px;
}
.pager label { font-size: 13px; color: var(--fg-soft); display: inline-flex; gap: 4px; align-items: center; }
.pg-btn {
  border: 1px solid var(--line); background: var(--panel); color: var(--fg);
  border-radius: var(--radius-ctl); width: 30px; height: 30px; cursor: pointer;
  font: inherit; line-height: 1;
}
.pg-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.pg-now { font-size: 14px; font-weight: 600; }
.pg-input { width: 64px; padding: 5px 8px; }
.pg-input::-webkit-outer-spin-button, .pg-input::-webkit-inner-spin-button { -webkit-appearance: none; }
</style>
