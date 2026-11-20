<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { api, type TrackingView, type CheckUpdateResult } from '../api/client'
import { loadStatusDict, statusLabel, lang, setLang } from '../composables/session'
import { t } from '../i18n'

// 单号详情（04 §5.7）：摘要卡 + 完整轨迹时间线；最新事件在上。
const route = useRoute()
const item = ref<TrackingView | null>(null)
const loading = ref(true)
const error = ref('')
const checkFeedback = ref('')
const checking = ref(false)

// 轨迹翻译（04 §6 增值项；R12 修订）：语言收敛为 en↔zh，用全局 lang
// （session.ts 'pt_lang'，与临时快查/结果列表共享）；切换后带参重新拉取，
// 服务端 LibreTranslate/缓存降级安全。
const LANGS = computed(() => [
  { code: '', label: t('track.lang_orig') },
  { code: 'zh', label: t('track.lang_zh') },
])
const translating = ref(false)

onMounted(async () => {
  await loadStatusDict()
  await reload()
})

async function reload() {
  translating.value = lang.value !== ''
  loading.value = item.value === null
  error.value = ''
  try {
    const id = String(route.params.id)
    const { data } = await api.get<TrackingView>(`/api/v1/trackings/${id}`, {
      lang: lang.value || undefined,
    })
    item.value = data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
    translating.value = false
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
          <label class="lang-wrap" for="lang-select">
            {{ t('track.lang') }}
            <select id="lang-select" :value="lang" :disabled="translating"
                    @change="setLang(($event.target as HTMLSelectElement).value); reload()">
              <option v-for="l in LANGS" :key="l.code" :value="l.code">
                {{ l.label }}
              </option>
            </select>
          </label>
        </div>
        <p v-if="checkFeedback" class="ok-box" role="status">{{ checkFeedback }}</p>
        <p v-if="translating" class="hint" role="status">{{ t('track.translating') }}</p>
        <p v-if="item.last_success_at" class="hint">
          {{ t('track.last_success', { time: fmtTime(item.last_success_at) }) }}
          <template v-if="item.next_sync_at">
            {{ t('track.next_sync', { time: fmtTime(item.next_sync_at) }) }}
          </template>
        </p>
        <p class="hint">{{ t('track.check_note') }}</p>
      </div>

      <div class="card">
        <h3>{{ t('track.timeline_title') }}</h3>
        <p v-if="eventsDesc.length === 0" class="hint" role="status">
          {{ t('track.no_events') }}
        </p>
        <ol v-else class="timeline">
          <li v-for="(ev, i) in eventsDesc" :key="i">
            <div class="ev-head">
              <span class="badge">{{ ev.label_zh || statusLabel(ev.status_key) }}</span>
              <span class="ev-time">{{ fmtTime(ev.occurred_at) }}</span>
            </div>
            <p v-if="ev.description" class="ev-desc">{{ ev.description }}</p>
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
.lang-wrap { display: flex; gap: 8px; align-items: center; font-size: 13px; color: var(--fg-soft); margin-left: auto; }
.lang-wrap select { width: auto; }
.sim-flag { font-weight: 700; }
.timeline { list-style: none; padding: 0; margin: 0; }
.timeline li { padding: 12px 0; border-bottom: 1px solid var(--line); }
.timeline li:last-child { border-bottom: none; }
.ev-head { display: flex; gap: 12px; align-items: center; }
.ev-time { color: var(--fg-soft); font-size: 13px; }
.ev-desc { margin: 6px 0 0; }
.conf { font-style: italic; }
</style>
