<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, type StatsView } from '../api/client'
import { loadStatusDict, statusLabel } from '../composables/session'
import { t } from '../i18n'

// 查询统计（04 §5.10）：只展示服务端口径的客户自己的历史汇总。
const stats = ref<StatsView | null>(null)
const days = ref(30)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  await loadStatusDict()
  await load()
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get<StatsView>('/api/v1/stats', { days: days.value })
    stats.value = data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

function labelOf(key: string): string {
  return statusLabel(key)
}

const distribution = computed(() => {
  if (!stats.value) return []
  return Object.entries(stats.value.status_distribution)
    .sort((a, b) => b[1] - a[1])
    .map(([key, n]) => ({ key, label: labelOf(key), n }))
})

const maxDaily = computed(() =>
  Math.max(1, ...(stats.value?.daily ?? []).map((d) => d.submissions)))
</script>

<template>
  <section>
    <h1 class="page-title">{{ t('stats.title') }}</h1>
    <p class="page-sub">{{ t('stats.sub') }}</p>

    <div class="card range">
      <label>{{ t('stats.range') }}
        <select v-model.number="days" @change="load">
          <option :value="7">{{ t('stats.days7') }}</option>
          <option :value="30">{{ t('stats.days30') }}</option>
          <option :value="90">{{ t('stats.days90') }}</option>
          <option :value="365">{{ t('stats.days365') }}</option>
        </select>
      </label>
    </div>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">{{ t('common.loading') }}</p>

    <template v-else-if="stats">
      <div class="cards-row">
        <div class="card stat">
          <p class="stat-label">{{ t('stats.stat.submissions') }}</p>
          <p class="stat-num">{{ stats.submissions }}</p>
        </div>
        <div class="card stat">
          <p class="stat-label">{{ t('stats.stat.trackings') }}</p>
          <p class="stat-num">{{ stats.tracking_count }}</p>
        </div>
        <div class="card stat">
          <p class="stat-label">{{ t('stats.stat.charged') }}</p>
          <p class="stat-num">{{ stats.points_charged }}{{ t('common.points_suffix') }}</p>
        </div>
        <div class="card stat">
          <p class="stat-label">{{ t('stats.stat.waived') }}</p>
          <p class="stat-num">{{ stats.waived_count }}</p>
        </div>
      </div>

      <div class="card">
        <h3>{{ t('stats.dist_title') }}</h3>
        <p v-if="distribution.length === 0" class="hint">{{ t('stats.no_dist') }}</p>
        <table v-else class="list">
          <thead><tr><th>{{ t('common.th.status') }}</th><th>{{ t('stats.th.count') }}</th></tr></thead>
          <tbody>
            <tr v-for="d in distribution" :key="d.key">
              <td><span class="badge">{{ d.label }}</span></td>
              <td>{{ d.n }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>{{ t('stats.trend_title') }}</h3>
        <p v-if="stats.daily.length === 0" class="hint">{{ t('stats.no_daily') }}</p>
        <ul v-else class="bars" role="img" :aria-label="t('stats.bars_aria')">
          <li v-for="d in stats.daily" :key="d.date">
            <span class="bar" :style="{ height: `${(d.submissions / maxDaily) * 100}%` }"></span>
            <span class="bar-label">{{ d.date.slice(5) }}</span>
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>

<style scoped>
.range select { margin-left: 8px; }
.cards-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 16px 0; }
.stat-num { font-size: 26px; font-weight: 700; margin: 4px 0; }
.stat-label { color: var(--fg-soft); font-size: 13px; margin: 0; }
.bars { display: flex; align-items: flex-end; gap: 6px; height: 140px; list-style: none; padding: 0; margin: 0; }
.bars li { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; height: 100%; }
.bar { background: var(--brand-soft, #bde); border-radius: 4px 4px 0 0; min-height: 4px; }
.bar-label { font-size: 10px; color: var(--fg-soft); text-align: center; }
@media (max-width: 860px) { .cards-row { grid-template-columns: 1fr 1fr; } }
</style>
