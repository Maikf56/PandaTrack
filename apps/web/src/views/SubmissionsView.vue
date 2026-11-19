<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type OperationSummary } from '../api/client'

// 提交记录（04 §5.9）：操作 ID/创建时间/条数/状态/扣费/查看进度。
const items = ref<OperationSummary[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const { data } = await api.get<OperationSummary[]>('/api/v1/operations', { limit: 100 })
    items.value = data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
})

const STATE_TEXT: Record<string, string> = {
  accepted: '已受理',
  processing: '查询中',
  completed: '已完成',
  failed: '处理失败',
}

function fmt(t?: string): string {
  return t ? new Date(t).toLocaleString() : '—'
}
</script>

<template>
  <section>
    <h1 class="page-title">提交记录</h1>
    <p class="page-sub">每次操作的受理状态、扣费与批次数；结果可在结果列表长期找回。</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>
    <p v-else-if="items.length === 0" class="hint" role="status">
      还没有提交记录。先粘贴 USPS 单号开始查询，提交后这里会显示受理状态与实际扣费。
    </p>

    <table v-else class="list">
      <thead>
        <tr>
          <th>操作 ID</th>
          <th>创建时间</th>
          <th>条数</th>
          <th>状态</th>
          <th>实际扣费</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="op in items" :key="op.id">
          <td class="mono">{{ op.id }}</td>
          <td>{{ fmt(op.created_at) }}</td>
          <td>{{ op.total_count }}（有效 {{ op.valid_count }}）</td>
          <td>{{ STATE_TEXT[op.state] ?? op.state }}</td>
          <td>{{ op.points_charged }} 积分</td>
          <td><RouterLink :to="`/results?op=${op.id}`">查看进度</RouterLink></td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
