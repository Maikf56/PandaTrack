<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api, type ExportJobView, type GroupView, type BatchView } from '../api/client'

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
    error.value = '请先选择导出范围对应的组或批次'
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

const SCOPE_TEXT: Record<string, string> = {
  all: '全部结果', group: '当前组', batch: '当前批次',
}

function fmt(t?: string | null): string {
  return t ? new Date(t).toLocaleString() : '—'
}
</script>

<template>
  <section>
    <h1 class="page-title">导出任务</h1>
    <p class="page-sub">
      导出结果为 CSV 文件；下载链接短期有效，过期后请重新导出。
    </p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>

    <div class="card new-export">
      <label>导出范围
        <select v-model="scope">
          <option value="all">全部结果</option>
          <option value="group">指定组</option>
          <option value="batch">指定批次</option>
        </select>
      </label>
      <select v-if="scope === 'group'" v-model="scopeRef">
        <option value="" disabled>选择组</option>
        <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
      </select>
      <select v-if="scope === 'batch'" v-model="scopeRef">
        <option value="" disabled>选择批次</option>
        <option v-for="b in batches" :key="b.id" :value="b.id">
          {{ b.id.slice(0, 8) }}…（{{ b.total_count }} 条，{{ b.created_at.slice(0, 10) }}）
        </option>
      </select>
      <button class="btn sm" :disabled="busy" @click="create">
        {{ busy ? '生成中…' : '生成并下载' }}
      </button>
    </div>

    <p v-if="loading" class="hint" role="status">正在加载…</p>
    <p v-else-if="items.length === 0" class="hint" role="status">还没有导出任务。</p>

    <table v-else class="list">
      <thead>
        <tr>
          <th>范围</th><th>创建时间</th><th>行数</th><th>格式</th><th>有效期</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in items" :key="e.id">
          <td>{{ SCOPE_TEXT[e.scope] ?? e.scope }}</td>
          <td>{{ fmt(e.created_at) }}</td>
          <td>{{ e.row_count }}</td>
          <td>{{ e.format.toUpperCase() }}</td>
          <td>
            <span v-if="e.expired" class="expired" role="status">文件已过期，请重新导出</span>
            <span v-else>{{ fmt(e.expires_at) }} 前有效</span>
          </td>
          <td>
            <button v-if="e.expired || !e.download_url" class="btn sm ghost" @click="regenerate(e)">
              重新导出
            </button>
            <a v-else :href="e.download_url" target="_blank">下载</a>
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
