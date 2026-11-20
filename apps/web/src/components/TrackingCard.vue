<script setup lang="ts">
import { ref, computed } from 'vue'
import { api, type TrackingView } from '../api/client'
import { statusLabel } from '../composables/session'
import { t } from '../i18n'

// 可展开单号卡（P15 三级页面第三层，对齐竞品）：
// 收起=单号+状态+最新事件；展开=完整轨迹时间线+统计行+检查更新。
const props = defineProps<{
  item: TrackingView
  flash?: boolean
  showGroup?: boolean
}>()

const open = ref(false)
const checking = ref(false)
const feedback = ref('')

const events = computed(() => {
  const evs = [...(props.item.events ?? [])]
  evs.sort((a, b) => (b.occurred_at ?? '').localeCompare(a.occurred_at ?? ''))
  return evs
})
const latest = computed(() => events.value[0])

function fmtTime(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function fmtShort(s?: string | null): string {
  if (!s) return ''
  const d = new Date(s)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

async function checkUpdate() {
  if (checking.value) return
  checking.value = true
  feedback.value = ''
  try {
    const { data } = await api.post<{ customer_tracking_id: string; fresh: boolean; will_fetch: boolean }[]>(
      '/api/v1/check-updates', { customer_tracking_ids: [props.item.id] })
    feedback.value = data[0]?.fresh
      ? t('card.fresh_reuse')
      : t('card.fresh_check')
  } catch (e) {
    feedback.value = (e as { message: string }).message
  } finally {
    checking.value = false
  }
}

async function copyNumber() {
  await navigator.clipboard?.writeText(props.item.normalized_number)
}
</script>

<template>
  <div class="tcard" :class="{ flash, open }">
    <button class="tcard-head" :aria-expanded="open" @click="open = !open">
      <span class="caret" aria-hidden="true">▸</span>
      <span class="mono num">{{ item.normalized_number }}</span>
      <span class="badge" :class="{ terminal: item.is_terminal }">
        {{ item.label_zh || statusLabel(item.status_key) }}
      </span>
      <span class="desc">{{ latest?.description || latest?.label_zh || t('card.no_events') }}</span>
      <span class="hint time">{{ fmtShort(latest?.occurred_at) }}</span>
    </button>

    <div v-if="open" class="tcard-body">
      <div class="body-toolbar">
        <span class="hint">USPS</span>
        <button class="linklike" @click="copyNumber">{{ t('card.copy_number') }}</button>
        <button class="linklike" :disabled="checking" @click="checkUpdate">
          {{ checking ? t('card.checking') : t('common.check_update') }}
        </button>
        <RouterLink class="linklike" :to="`/results/${item.id}`">{{ t('card.detail_page') }}</RouterLink>
      </div>
      <p v-if="feedback" class="hint fb" role="status">{{ feedback }}</p>

      <div class="timeline-wrap">
        <p class="hint tl-title">{{ t('card.tl_title') }}</p>
        <p v-if="events.length === 0" class="hint" role="status">
          {{ t('card.no_events_long') }}
        </p>
        <ol v-else class="timeline">
          <li v-for="(ev, i) in events" :key="i" :class="{ first: i === 0 }">
            <span class="node" aria-hidden="true"></span>
            <div class="ev">
              <p class="ev-title">{{ ev.description || ev.label_zh || statusLabel(ev.status_key) }}</p>
              <p class="hint">{{ ev.location || '' }} · {{ fmtTime(ev.occurred_at) }}</p>
            </div>
          </li>
        </ol>
      </div>

      <div class="stats">
        <div><span class="hint">{{ t('card.orig_status') }}</span><strong>{{ item.label_zh || statusLabel(item.status_key) }}</strong></div>
        <div><span class="hint">{{ t('card.query_count') }}</span><strong>—</strong></div>
        <div><span class="hint">{{ t('card.last_query') }}</span><strong>{{ fmtTime(item.last_success_at) }}</strong></div>
        <div><span class="hint">{{ t('card.created') }}</span><strong>{{ fmtTime(item.batch_created_at) }}</strong></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tcard {
  border: 1px solid var(--line); border-radius: var(--radius-panel);
  background: var(--panel); margin-bottom: 10px; overflow: hidden;
  transition: box-shadow var(--dur) ease-out;
}
.tcard:hover { box-shadow: var(--shadow-1); }
.tcard.flash { animation: card-flash 1.2s ease-out; }
@keyframes card-flash {
  0% { border-color: var(--brand); box-shadow: 0 0 0 2px var(--brand-soft); }
  100% { border-color: var(--line); }
}
.tcard-head {
  display: flex; align-items: center; gap: 10px; width: 100%;
  padding: 12px 16px; border: 0; background: transparent; cursor: pointer;
  font: inherit; text-align: left;
}
.caret { color: var(--fg-soft); transition: transform 140ms ease-out; flex: none; }
.open .caret { transform: rotate(90deg); }
.num { font-size: 14px; flex: none; }
.desc {
  flex: 1; min-width: 0; color: var(--fg-soft); font-size: 13px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.time { flex: none; }
.tcard-body { border-top: 1px solid var(--line); padding: 12px 16px 16px; }
.body-toolbar { display: flex; gap: 16px; align-items: center; }
.linklike { color: var(--brand); text-decoration: none; cursor: pointer; font-size: 13px; }
button.linklike { background: none; border: 0; padding: 0; font: inherit; font-size: 13px; color: var(--brand); }
button.linklike:disabled { opacity: 0.5; cursor: not-allowed; }
.fb { margin: 6px 0 0; }
.timeline-wrap { margin-top: 12px; }
.tl-title { margin: 0 0 8px; }
.timeline { list-style: none; margin: 0; padding: 0 0 0 4px; }
.timeline li { position: relative; padding: 0 0 16px 22px; }
.timeline li::before {
  content: ''; position: absolute; left: 5px; top: 14px; bottom: -2px;
  width: 2px; background: var(--line);
}
.timeline li:last-child::before { display: none; }
.node {
  position: absolute; left: 0; top: 4px; width: 12px; height: 12px;
  border-radius: 999px; background: var(--line);
}
.timeline li.first .node { background: var(--brand); box-shadow: 0 0 0 3px var(--brand-soft); }
.ev-title { margin: 0; font-weight: 500; }
.ev p.hint { margin: 2px 0 0; }
.stats {
  display: flex; gap: 32px; flex-wrap: wrap; margin-top: 6px;
  padding-top: 12px; border-top: 1px solid var(--line);
}
.stats span { display: block; font-size: 12px; }
.stats strong { font-size: 14px; }
@media (max-width: 640px) {
  .tcard-head { flex-wrap: wrap; }
  .desc { width: 100%; }
}
</style>
