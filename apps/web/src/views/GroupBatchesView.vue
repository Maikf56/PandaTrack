<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type GroupView, type BatchView, type TrackingView, type CheckUpdateResult } from '../api/client'
import { loadStatusDict, lang } from '../composables/session'
import { t } from '../i18n'
import { hasUpdate, visibilityPolling, createChangeTracker } from '../composables/sse'
import StatusDistBar from '../components/StatusDistBar.vue'

// 结果列表 · 第二级（P15）：组内批次卡片（状态分布 + 最近查询）→ 点入批次单号。
const route = useRoute()
const groupId = computed(() => String(route.params.id))

const group = ref<GroupView | null>(null)
const batches = ref<BatchView[]>([])
const trackings = ref<TrackingView[]>([])
const loading = ref(true)
const error = ref('')

// 变化感知 + 轮询兜底（SSE 由 App 全局持有，页面只消费 hasUpdate）
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

watch([groupId, lang], () => { void reload() })

async function reload() {
  loading.value = batches.value.length === 0
  error.value = ''
  try {
    const [g, bs, ts] = await Promise.all([
      api.get<GroupView[]>('/api/v1/groups'),
      api.get<BatchView[]>(`/api/v1/groups/${groupId.value}/batches`, { limit: 100 }),
      api.get<TrackingView[]>('/api/v1/trackings', { lang: lang.value || undefined }),
    ])
    group.value = g.data.find((x) => x.id === groupId.value) ?? null
    batches.value = bs.data
    trackings.value = ts.data
    // 变化感知（以全部单号快照，跟踪跨页状态跃迁）
    const snapshot = new Map(ts.data.map((it) => [it.id, it.status_key]))
    tracker.feed(snapshot)
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

/** 批次完结度：用本组单号按 batch_id 聚合终态计数（batch_id=操作 public_id）。 */
const batchStats = computed(() => {
  const map = new Map<string, { terminal: number; total: number }>()
  for (const it of trackings.value) {
    if (!it.batch_id) continue
    const s = map.get(it.batch_id) ?? { terminal: 0, total: 0 }
    s.total++
    if (it.is_terminal) s.terminal++
    map.set(it.batch_id, s)
  }
  return map
})

function fmtTime(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 全组检查更新：非终态单号批量提交检查（不扣积分）。 */
const checking = ref(false)
const checkFeedback = ref('')
async function checkAllPending() {
  if (checking.value) return
  const ids = trackings.value
    .filter((it) => !it.is_terminal)
    .map((it) => it.id)
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

/** 导出本组（scope=group）。 */
const exporting = ref(false)
async function exportGroup() {
  if (exporting.value) return
  exporting.value = true
  try {
    await api.post('/api/v1/exports', { scope: 'group', scope_ref: groupId.value })
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
    <p class="crumb"><RouterLink to="/results">{{ t('nav.results') }}</RouterLink> › {{ group?.name ?? t('gb.crumb_group') }}</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">{{ t('common.loading') }}</p>

    <template v-else>
      <div v-if="group" class="card ghead">
        <div class="ghead-row">
          <h1 class="page-title">{{ group.name }} <span v-if="group.is_default" class="badge">{{ t('gb.default') }}</span></h1>
          <div class="actions">
            <button class="btn ghost sm" :disabled="checking" @click="checkAllPending">
              {{ checking ? t('card.checking') : t('common.check_update') }}
            </button>
            <button class="btn ghost sm" :disabled="exporting" @click="exportGroup">{{ t('common.export') }}</button>
          </div>
        </div>
        <p class="hint">{{ group.tracking_count }}{{ t('gb.numbers_unit') }} · {{ group.batch_count }}{{ t('gb.batches_unit') }}</p>
        <StatusDistBar :distribution="group.status_distribution" :total="group.tracking_count" />
        <p v-if="checkFeedback" class="ok-box" role="status">{{ checkFeedback }}</p>
      </div>

      <div v-if="batches.length === 0" class="card empty-state" role="status">
        <p>{{ t('gb.no_batches') }}</p>
        <RouterLink class="btn" to="/submit">{{ t('nav.submit') }}</RouterLink>
      </div>

      <div v-else class="batches">
        <div
          v-for="b in batches"
          :key="b.id"
          class="card bcard"
          role="link" tabindex="0"
          @click="$router.push(`/results/batch/${b.id}`)"
          @keydown.enter.prevent="$router.push(`/results/batch/${b.id}`)"
        >
          <div class="bcard-head">
            <span class="b-time">{{ fmtTime(b.created_at) }}</span>
            <span class="meta">{{ b.valid_count }}{{ t('gb.numbers_unit') }}</span>
            <span class="meta dim">{{ t('gb.last_query', { time: fmtTime(b.updated_at) }) }}</span>
            <span class="spacer"></span>
            <span class="badge" :class="{ terminal: (batchStats.get(b.id)?.terminal ?? 0) >= b.valid_count && b.valid_count > 0 }">
              {{ t('gb.terminal_badge', { n: batchStats.get(b.id)?.terminal ?? 0 }) }}
            </span>
          </div>
          <StatusDistBar
            :distribution="b.status_distribution ?? {}"
            :total="batchStats.get(b.id)?.total ?? 0"
          />
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.crumb { color: var(--fg-soft); font-size: 13px; margin: 0 0 8px; }
.crumb a { color: var(--fg-soft); text-decoration: none; }
.crumb a:hover { color: var(--brand); }
.ghead-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.actions { display: flex; gap: 8px; }
.batches { display: flex; flex-direction: column; gap: 12px; margin-top: 8px; }
.bcard { cursor: pointer; margin-bottom: 0; transition: box-shadow var(--dur) ease-out, border-color var(--dur) ease-out; }
.bcard:hover { box-shadow: var(--shadow-1); border-color: var(--brand-line); }
.bcard-head { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 4px; }
.b-time { font-weight: 700; font-size: 15px; }
.meta { color: var(--fg-soft); font-size: 13px; }
.meta.dim { font-size: 12px; }
.spacer { flex: 1; }
.badge.terminal { background: var(--ok-soft); color: var(--ok); }
</style>
