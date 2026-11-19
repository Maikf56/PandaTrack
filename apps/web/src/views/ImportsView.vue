<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type ImportJobView } from '../api/client'

// 导入任务（04 §5.9）：文件名/进度/成败跳过重复/失败原因/关联操作入口。
const items = ref<ImportJobView[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const { data } = await api.get<ImportJobView[]>('/api/v1/imports', { limit: 100 })
    items.value = data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
})

const STATUS_TEXT: Record<string, string> = {
  pending: '等待处理', processing: '处理中', done: '已完成', failed: '处理失败',
}

function fmt(t?: string): string {
  return t ? new Date(t).toLocaleString() : '—'
}
</script>

<template>
  <section>
    <h1 class="page-title">导入任务</h1>
    <p class="page-sub">文件批量导入的处理进度、成功与失败统计；失败原因均可下载查看。</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>
    <p v-else-if="items.length === 0" class="hint" role="status">
      还没有导入任务。需要大批量查单时，先上传单号文件创建导入任务。
    </p>

    <table v-else class="list">
      <thead>
        <tr>
          <th>文件名</th><th>创建时间</th><th>总行数</th><th>进度</th>
          <th>成功 / 失败</th><th>跳过 / 重复</th><th>状态</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="it in items" :key="it.id">
          <td class="mono">{{ it.file_name ?? '—' }}</td>
          <td>{{ fmt(it.created_at) }}</td>
          <td>{{ it.total }}</td>
          <td>{{ it.done }}/{{ it.total }}（入队 {{ it.enqueued }}）</td>
          <td>{{ it.success_count }} / {{ it.failed_count }}</td>
          <td>{{ it.skipped_count }} / {{ it.duplicate_count }}</td>
          <td>{{ STATUS_TEXT[it.status] ?? it.status }}</td>
          <td>
            <RouterLink v-if="it.operation_id" :to="`/results?op=${it.operation_id}`">
              查看结果
            </RouterLink>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
