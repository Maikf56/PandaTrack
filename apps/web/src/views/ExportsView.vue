<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api, type ExportJobView, type GroupView, type BatchView } from '../api/client'
import { t } from '../i18n'

// 导出任务（04 §5.9）：范围选择/短期下载链接/过期重新导出。
const items = ref<ExportJobView[]>([])
const groups = ref<GroupView[]>([])
const batches = ref<BatchView[]>([])
const scope = ref<'all' | 'group' | 'batch'>('all')
const scopeRef = ref('')
const loading = ref(true)
const error = ref('')
const busy = ref(false)

onMounted(async () => {
  // 从组批次页“导出”入口带 ?batch= 直达批次导出
  const presetBatch = useRoute().query.batch
  try {
    const [ex, gs, bs] = await Promise.all([
      api.get<ExportJobView[]>('/api/v1/exports'),
      api.get<GroupView[]>('/api/v1/groups'),
      api.get<BatchView[]>('/api/v1/batches', { limit: 50 }),
    ])
    items.value = ex.data
    groups.value = gs.data
    batches.value = bs.data
    if (typeof presetBatch === 'string' && presetBatch) {
      scope.value = 'batch'
      scopeRef.value = presetBatch
    }
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
})

async function create() {
  if (busy.value) return
  if (scope.value !== 'all' && !scopeRef.value) {
    error.value = t('exports.err_scope')
    return
  }
  busy.value = true
  error.value = ''
  try {
    const { data } = await api.post<ExportJobView>('/api/v1/exports', {
      scope: scope.value,
      scope_ref: scope.value === 'all' ? null : scopeRef.value,
    })
    items.value = [data, ...items.value]
    // 创建响应携带一次性短期下载链接，立即触发下载。
    if (data.download_url) window.open(data.download_url, '_blank')
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    busy.value = false
  }
}

async function regenerate(e: ExportJobView) {
  scope.value = e.scope as 'all' | 'group' | 'batch'
  scopeRef.value = e.scope_ref ?? ''
  await create()
}

function scopeText(s: string): string {
  if (s === 'all') return t('exports.scopec.all')
  if (s === 'group') return t('exports.scopec.group')
  if (s === 'batch') return t('exports.scopec.batch')
  return s
}

function fmt(s?: string | null): string {
  return s ? new Date(s).toLocaleString() : '—'
}
</script>

<template>
  <section>
    <h1 class="page-title">{{ t('exports.title') }}</h1>
    <p class="page-sub">
      {{ t('exports.sub') }}
    </p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>

    <div class="card new-export">
      <label>{{ t('exports.scope_label') }}
        <select v-model="scope">
          <option value="all">{{ t('exports.scope.all') }}</option>
          <option value="group">{{ t('exports.scope.group') }}</option>
          <option value="batch">{{ t('exports.scope.batch') }}</option>
        </select>
      </label>
      <select v-if="scope === 'group'" v-model="scopeRef">
        <option value="" disabled>{{ t('exports.pick_group') }}</option>
        <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
      </select>
      <select v-if="scope === 'batch'" v-model="scopeRef">
        <option value="" disabled>{{ t('exports.pick_batch') }}</option>
        <option v-for="b in batches" :key="b.id" :value="b.id">
          {{ t('exports.batch_option', { id: b.id.slice(0, 8), n: b.total_count, date: b.created_at.slice(0, 10) }) }}
        </option>
      </select>
      <button class="btn sm" :disabled="busy" @click="create">
        {{ busy ? t('exports.generating') : t('exports.generate') }}
      </button>
    </div>

    <p v-if="loading" class="hint" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="items.length === 0" class="hint" role="status">{{ t('exports.empty') }}</p>

    <table v-else class="list">
      <thead>
        <tr>
          <th>{{ t('exports.th.scope') }}</th><th>{{ t('common.th.created') }}</th><th>{{ t('exports.th.rows') }}</th><th>{{ t('exports.th.format') }}</th><th>{{ t('exports.th.validity') }}</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in items" :key="e.id">
          <td>{{ scopeText(e.scope) }}</td>
          <td>{{ fmt(e.created_at) }}</td>
          <td>{{ e.row_count }}</td>
          <td>{{ e.format.toUpperCase() }}</td>
          <td>
            <span v-if="e.expired" class="expired" role="status">{{ t('exports.expired') }}</span>
            <span v-else>{{ t('exports.valid_until', { time: fmt(e.expires_at) }) }}</span>
          </td>
          <td>
            <button v-if="e.expired || !e.download_url" class="btn sm ghost" @click="regenerate(e)">
              {{ t('exports.reexport') }}
            </button>
            <a v-else :href="e.download_url" target="_blank">{{ t('common.download') }}</a>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.new-export { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.expired { color: var(--danger, #b00); font-size: 13px; }
</style>
