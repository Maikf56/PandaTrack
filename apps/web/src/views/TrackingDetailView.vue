<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { api, type TrackingView, type CheckUpdateResult } from '../api/client'
import { loadStatusDict, statusLabel } from '../composables/session'

// 单号详情（04 §5.7）：摘要卡 + 完整轨迹时间线；最新事件在上。
const route = useRoute()
const item = ref<TrackingView | null>(null)
const loading = ref(true)
const error = ref('')
const checkFeedback = ref('')
const checking = ref(false)

onMounted(async () => {
  await loadStatusDict()
  await reload()
})

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const id = String(route.params.id)
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
  evs.sort((a, b) => (b.event_time ?? '').localeCompare(a.event_time ?? ''))
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
      ? '将沿用现有结果（未创建新的查询任务）。'
      : '已提交检查；结果在后台更新，稍后查看。'
  } catch (e) {
    checkFeedback.value = ''
    error.value = (e as { message: string }).message
  } finally {
    checking.value = false
  }
}

function fmtTime(t?: string | null): string {
  if (!t) return ''
  return new Date(t).toLocaleString()
}
</script>

<template>
  <section>
    <p v-if="loading" class="hint" role="status">正在加载…</p>
    <p v-if="error" class="error-box" role="alert">{{ error }}</p>

    <template v-if="item">
      <h1 class="page-title mono">{{ item.normalized_number }}</h1>
      <p class="page-sub">
        当前状态：<span class="badge" :class="{ terminal: item.is_terminal }">
          {{ item.label_zh || statusLabel(item.status_key) }}
        </span>
      </p>

      <!-- 模拟数据标记（04 §5.7/验收 12）：醒目，不用正常样式隐藏 -->
      <p v-if="item.simulated" class="error-box sim-flag" role="alert">
        模拟数据，仅用于测试
      </p>

      <div class="card">
        <div class="actions">
          <button class="btn" :disabled="checking" @click="checkUpdate">
            {{ checking ? '提交检查中…' : '检查更新' }}
          </button>
          <RouterLink class="btn ghost" to="/results">返回结果列表</RouterLink>
        </div>
        <p v-if="checkFeedback" class="ok-box" role="status">{{ checkFeedback }}</p>
        <p v-if="item.last_success_at" class="hint">
          最近有效更新：{{ fmtTime(item.last_success_at) }}
          <template v-if="item.next_sync_at">
            · 后台保鲜计划时间：{{ fmtTime(item.next_sync_at) }}
          </template>
        </p>
        <p class="hint">「检查更新」由服务端决定是否创建新任务；沿用旧结果时会明确说明。</p>
      </div>

      <div class="card">
        <h3>完整轨迹</h3>
        <p v-if="eventsDesc.length === 0" class="hint" role="status">
          暂时还没有可展示的轨迹事件；不等于确认包裹不存在。
        </p>
        <ol v-else class="timeline">
          <li v-for="(ev, i) in eventsDesc" :key="i">
            <div class="ev-head">
              <span class="badge">{{ ev.label_zh || statusLabel(ev.status_key) }}</span>
              <span class="ev-time">{{ fmtTime(ev.event_time) }}</span>
            </div>
            <p v-if="ev.description" class="ev-desc">{{ ev.description }}</p>
            <p v-if="ev.location" class="hint">{{ ev.location }}</p>
            <p
              v-if="ev.time_confidence && ev.time_confidence !== 'exact'"
              class="hint conf"
              role="note"
            >
              时间按来源原文记录，时区可能需要确认
            </p>
          </li>
        </ol>
      </div>
    </template>
  </section>
</template>

<style scoped>
.actions { display: flex; gap: 12px; flex-wrap: wrap; }
.sim-flag { font-weight: 700; }
.timeline { list-style: none; padding: 0; margin: 0; }
.timeline li { padding: 12px 0; border-bottom: 1px solid var(--line); }
.timeline li:last-child { border-bottom: none; }
.ev-head { display: flex; gap: 12px; align-items: center; }
.ev-time { color: var(--fg-soft); font-size: 13px; }
.ev-desc { margin: 6px 0 0; }
.conf { font-style: italic; }
</style>
