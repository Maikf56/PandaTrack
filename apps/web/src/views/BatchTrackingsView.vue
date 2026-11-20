<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type BatchView, type TrackingView, type CheckUpdateResult } from '../api/client'
import { loadStatusDict, session, lang } from '../composables/session'
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

watch([batchId, lang], () => { void reload() })

async function reload() {
  loading.value = items.value.length === 0
  error.value = ''
  try {
    const [bs, ts] = await Promise.all([
      api.get<BatchView[]>('/api/v1/batches', { limit: 100 }),
      api.get<TrackingView[]>('/api/v1/trackings', { lang: lang.value || undefined }),
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

const dist = computed(() => {
  const d: Record<string, number> = {}
  for (const it of items.value) {
    const k = it.status_key || 'other'
    d[k] = (d[k] ?? 0) + 1
  }
  return d
})

const terminalCount = computed(() => items.value.filter((it) => it.is_terminal).length)

function fmtTime(t?: string | null): string {
  if (!t) return '—'
  const d = new Date(t)
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 批量检查更新：默认提交全部非终态项（最常见的重查动机），不扣积分。 */
const checking = ref(false)
const checkFeedback = ref('')
async function checkPending() {
  if (checking.value) return
  const ids = items.value.filter((it) => !it.is_terminal).map((it) => it.id)
  if (ids.length === 0) {
    checkFeedback.value = '本批所有单号都已完结。'
    return
  }
  checking.value = true
  try {
    const { data } = await api.post<CheckUpdateResult[]>('/api/v1/check-updates', {
      customer_tracking_ids: ids,
    })
    const fresh = data.filter((r) => r.fresh).length
    checkFeedback.value =
      `已提交检查 ${data.length} 项（${fresh} 项沿用现有结果，其余已创建检查任务）；结果在后台更新。`
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
    checkFeedback.value = '导出任务已创建，可在「导出任务」页下载。'
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <section>
    <p class="crumb"><RouterLink to="/results">我的查询</RouterLink> › 批次</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <template v-else>
      <div class="card bhead">
        <div class="bhead-row">
          <div>
            <h1 class="page-title">{{ fmtTime(batch?.created_at) }} 批次</h1>
            <p class="hint">
              共 {{ items.length }} 个单号 · 已完结 {{ terminalCount }} · 最近查询 {{ fmtTime(batch?.updated_at) }}
              <template v-if="batch"> · 扣费 {{ batch.points_charged }} 积分</template>
            </p>
          </div>
          <div class="actions">
            <button class="btn ghost sm" :disabled="checking" @click="checkPending">
              {{ checking ? '检查中…' : '重新查询未完结' }}
            </button>
            <button class="btn ghost sm" :disabled="exporting" @click="exportBatch">导出</button>
          </div>
        </div>
        <StatusDistBar :distribution="dist" :total="items.length" />
        <p v-if="checkFeedback" class="ok-box" role="status">{{ checkFeedback }}</p>
      </div>

      <div class="card filters">
        <input v-model="search" placeholder="批量搜索单号" aria-label="批量搜索单号" />
        <select v-model="filterStatus" aria-label="按任务状态筛选">
          <option value="">全部任务状态</option>
          <option v-for="s in session.statusDict?.statuses ?? []" :key="s.key" :value="s.key">
            {{ s.label_zh }}
          </option>
        </select>
      </div>

      <div v-if="items.length === 0" class="card empty-state" role="status">
        <p>本批暂时没有可展示的单号（可能尚未投影完成，稍后刷新）。</p>
        <button class="btn ghost" @click="reload">刷新</button>
      </div>
      <div v-else-if="filtered.length === 0" class="card empty-state" role="status">
        <p>没有符合筛选条件的单号。</p>
        <button class="btn ghost" @click="search = ''; filterStatus = ''">清除筛选</button>
      </div>

      <div v-else class="cards">
        <TrackingCard
          v-for="it in filtered"
          :key="it.id"
          :item="it"
          :flash="tracker.changedIds.value.has(it.id)"
        />
        <p class="hint scope-note">
          同一单号多次提交时归入最近一次批次；如需看其他批次的结果，请从上一级对应批次进入。
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
.actions { display: flex; gap: 8px; }
.filters { display: flex; gap: 12px; flex-wrap: wrap; }
.filters input, .filters select { width: auto; min-width: 200px; }
.cards { margin-top: 8px; }
.scope-note { margin-top: 4px; }
</style>
