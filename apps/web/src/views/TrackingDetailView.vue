<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { api, type TrackingView, type CheckUpdateResult } from '../api/client'
import { loadStatusDict, statusLabel } from '../composables/session'
import { t } from '../i18n'

// 单号详情（04 §5.7）：摘要卡 + 完整轨迹时间线；最新事件在上。
const route = useRoute()
const item = ref<TrackingView | null>(null)
const loading = ref(true)
const error = ref('')
const checkFeedback = ref('')
const checking = ref(false)

// 轨迹翻译（P17 竞品式）：默认英文原文直出，右上「翻译」切中文
// （USPS 词典优先、机翻兜底），「显示原文」切回；原文永不覆盖。
const translated = ref(false)
const translating = ref(false)
const fallbackZh = ref<Map<string, string>>(new Map())

const hasDictZh = computed(() =>
  eventsDesc.value.some((e) => e.description_zh || fallbackZh.value.get(e.description || '')))

function titleOf(e: TrackingView['events'][number]): string {
  if (!translated.value) return e.description || e.label_zh || statusLabel(e.status_key)
  return e.description_zh || fallbackZh.value.get(e.description || '')
    || e.description || e.label_zh || statusLabel(e.status_key)
}

function subOf(e: TrackingView['events'][number]): string {
  if (!translated.value) return ''
  const zh = e.description_zh || fallbackZh.value.get(e.description || '') || ''
  return zh && zh !== e.description ? (e.description || '') : ''
}

async function toggleTranslate() {
  if (translated.value) {
    translated.value = false
    return
  }
  if (hasDictZh.value) {
    translated.value = true
    return
  }
  translating.value = true
  try {
    const id = String(route.params.id)
    const { data } = await api.get<TrackingView>(`/api/v1/trackings/${id}`, { lang: 'zh' })
    const m = new Map<string, string>()
    for (const e of data.events ?? []) {
      if (e.description_zh) m.set(e.description || '', e.description_zh)
    }
    fallbackZh.value = m
    translated.value = m.size > 0
  } catch {
    translated.value = true
  } finally {
    translating.value = false
  }
}

onMounted(async () => {
  await loadStatusDict()
  await reload()
})

async function reload() {
  loading.value = item.value === null
  error.value = ''
  try {
    const id = String(route.params.id)
    // 原文请求（lang 留空）：事件同时带英文原文与词典中文，前端本地切换
    const { data } = await api.get<TrackingView>(`/api/v1/trackings/${id}`)
    item.value = data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

const eventsDesc = computed(() => {
  if (!item.value) return []
  const evs = [...(item.value.events ?? [])]
  evs.sort((a, b) => (b.occurred_at ?? '').localeCompare(a.occurred_at ?? ''))
  return evs
})

async function checkUpdate() {
  if (!item.value || checking.value) return
  checking.value = true
  checkFeedback.value = ''
  try {
    const { data } = await api.post<CheckUpdateResult[]>('/api/v1/check-updates', {
      customer_tracking_ids: [item.value.id],
    })
    const r = data[0]
    checkFeedback.value = r?.fresh
      ? t('track.fresh_feedback')
      : t('track.check_feedback')
  } catch (e) {
    checkFeedback.value = ''
    error.value = (e as { message: string }).message
  } finally {
    checking.value = false
  }
}

function fmtTime(s?: string | null): string {
  if (!s) return ''
  return new Date(s).toLocaleString()
}
</script>

<template>
  <section>
    <p v-if="loading" class="hint" role="status">{{ t('common.loading') }}</p>
    <p v-if="error" class="error-box" role="alert">{{ error }}</p>

    <template v-if="item">
      <h1 class="page-title mono">{{ item.normalized_number }}</h1>
      <p class="page-sub">
        {{ t('track.current_status') }}<span class="badge" :class="{ terminal: item.is_terminal }">
          {{ item.label_zh || statusLabel(item.status_key) }}
        </span>
      </p>

      <!-- 模拟数据标记（04 §5.7/验收 12）：醒目，不用正常样式隐藏 -->
      <p v-if="item.simulated" class="error-box sim-flag" role="alert">
        {{ t('track.simulated') }}
      </p>

      <div class="card">
        <div class="actions">
          <button class="btn" :disabled="checking" @click="checkUpdate">
            {{ checking ? t('common.checking') : t('common.check_update') }}
          </button>
          <RouterLink class="btn ghost" to="/results">{{ t('track.back_results') }}</RouterLink>
        </div>
        <p v-if="checkFeedback" class="ok-box" role="status">{{ checkFeedback }}</p>
        <p v-if="translating" class="hint" role="status">{{ t('card.translating') }}</p>
        <p v-if="item.last_success_at" class="hint">
          {{ t('track.last_success', { time: fmtTime(item.last_success_at) }) }}
          <template v-if="item.next_sync_at">
            {{ t('track.next_sync', { time: fmtTime(item.next_sync_at) }) }}
          </template>
        </p>
        <p class="hint">{{ t('track.check_note') }}</p>
      </div>

      <div class="card">
        <div class="tl-head">
          <h3>{{ t('track.timeline_title') }}</h3>
          <button class="linklike tr-toggle" :disabled="translating" @click="toggleTranslate">
            {{ translating
              ? t('card.translating')
              : (translated ? t('card.show_original') : t('card.translate')) }}
          </button>
        </div>
        <p v-if="eventsDesc.length === 0" class="hint" role="status">
          {{ t('track.no_events') }}
        </p>
        <ol v-else class="timeline">
          <li v-for="(ev, i) in eventsDesc" :key="i">
            <div class="ev-head">
              <span class="badge">{{ ev.label_zh || statusLabel(ev.status_key) }}</span>
              <span class="ev-time">{{ fmtTime(ev.occurred_at) }}</span>
            </div>
            <p class="ev-desc">{{ titleOf(ev) }}</p>
            <p v-if="subOf(ev)" class="ev-sub">{{ subOf(ev) }}</p>
            <p v-if="ev.location" class="hint">{{ ev.location }}</p>
            <p
              v-if="ev.time_confidence && ev.time_confidence !== 'exact'"
              class="hint conf"
              role="note"
            >
              {{ t('track.time_note') }}
            </p>
          </li>
        </ol>
      </div>
    </template>
  </section>
</template>

<style scoped>
.actions { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.tl-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.tr-toggle { background: none; border: 0; padding: 0; font: inherit; font-size: 13px; color: var(--brand); cursor: pointer; font-weight: 600; }
.tr-toggle:disabled { opacity: 0.5; cursor: not-allowed; }
.sim-flag { font-weight: 700; }
.timeline { list-style: none; padding: 0; margin: 0; }
.timeline li { padding: 12px 0; border-bottom: 1px solid var(--line); }
.timeline li:last-child { border-bottom: none; }
.ev-head { display: flex; gap: 12px; align-items: center; }
.ev-time { color: var(--fg-soft); font-size: 13px; }
.ev-desc { margin: 6px 0 0; font-weight: 600; }
.ev-sub { margin: 1px 0 0; color: var(--fg-soft); font-size: 12.5px; }
.conf { font-style: italic; }
</style>
