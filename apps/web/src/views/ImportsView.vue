<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type ImportJobView } from '../api/client'
import { t } from '../i18n'

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

function statusText(s: string): string {
  if (s === 'pending') return t('imports.state.pending')
  if (s === 'processing') return t('imports.state.processing')
  if (s === 'done') return t('imports.state.done')
  if (s === 'failed') return t('imports.state.failed')
  return s
}

function fmt(s?: string): string {
  return s ? new Date(s).toLocaleString() : '—'
}
</script>

<template>
  <section>
    <h1 class="page-title">{{ t('imports.title') }}</h1>
    <p class="page-sub">{{ t('imports.sub') }}</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="items.length === 0" class="hint" role="status">
      {{ t('imports.empty') }}
    </p>

    <table v-else class="list">
      <thead>
        <tr>
          <th>{{ t('imports.th.file') }}</th><th>{{ t('common.th.created') }}</th><th>{{ t('imports.th.total') }}</th><th>{{ t('imports.th.progress') }}</th>
          <th>{{ t('imports.th.ok_fail') }}</th><th>{{ t('imports.th.skip_dup') }}</th><th>{{ t('common.th.status') }}</th><th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="it in items" :key="it.id">
          <td class="mono">{{ it.file_name ?? '—' }}</td>
          <td>{{ fmt(it.created_at) }}</td>
          <td>{{ it.total }}</td>
          <td>{{ t('imports.progress', { done: it.done, total: it.total, enq: it.enqueued }) }}</td>
          <td>{{ it.success_count }} / {{ it.failed_count }}</td>
          <td>{{ it.skipped_count }} / {{ it.duplicate_count }}</td>
          <td>{{ statusText(it.status) }}</td>
          <td>
            <RouterLink v-if="it.operation_id" :to="`/results?op=${it.operation_id}`">
              {{ t('common.view_results') }}
            </RouterLink>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
