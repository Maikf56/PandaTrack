<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, type LedgerEntry, type TrackingView } from '../api/client'
import { loadSession, session, loadStatusDict } from '../composables/session'

// 工作台首页（04 §5.5）：现在需要关注什么 + 我刚才做了什么。
const loading = ref(true)
const error = ref('')
const recentLedger = ref<LedgerEntry[]>([])
const recentResults = ref<TrackingView[]>([])

onMounted(async () => {
  await loadSession(true)
  await loadStatusDict()
  try {
    const [w, t] = await Promise.all([
      api.get<LedgerEntry[]>('/api/v1/ledger', { limit: 5 }),
      api.get<TrackingView[]>('/api/v1/trackings'),
    ])
    recentLedger.value = w.data
    recentResults.value = t.data.slice(0, 5)
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
})

const me = computed(() => session.me)
const statusCount = computed(() => recentResults.value.length)
</script>

<template>
  <section>
    <h1 class="page-title">工作台</h1>
    <p class="page-sub">查看余额、处理进度和最近操作。</p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <template v-else>
      <div class="cards-row">
        <div class="card stat">
          <p class="stat-label">当前积分余额</p>
          <p class="stat-num" role="status">{{ me?.balance ?? '—' }}</p>
        </div>
        <div class="card stat">
          <p class="stat-label">最近结果条数</p>
          <p class="stat-num">{{ statusCount }}</p>
        </div>
        <div class="card stat">
          <p class="stat-label">累计消耗</p>
          <p class="stat-num">{{ me?.balance !== undefined ? '' : '' }}<RouterLink to="/wallet">去积分中心查看</RouterLink></p>
        </div>
      </div>

      <div class="card main-actions">
        <RouterLink class="btn" to="/quick">提交单号查询</RouterLink>
        <RouterLink class="btn ghost" to="/results">查看结果列表</RouterLink>
        <RouterLink class="btn ghost" to="/wallet">积分中心</RouterLink>
      </div>

      <div class="card">
        <h3>最近查询结果</h3>
        <p v-if="recentResults.length === 0" class="hint" role="status">
          还没有查询记录。先粘贴 USPS 单号并开始查询，提交后这里会显示本次实际扣费和进度。
        </p>
        <table v-else class="list">
          <thead>
            <tr><th>单号</th><th>状态</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="it in recentResults" :key="it.id">
              <td class="mono">{{ it.normalized_number }}</td>
              <td><span class="badge" :class="{ terminal: it.is_terminal }">{{ it.label_zh }}</span></td>
              <td><RouterLink :to="`/results/${it.id}`">详情</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.cards-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.stat-num { font-size: 26px; font-weight: 700; margin: 4px 0; }
.stat-label { color: var(--fg-soft); font-size: 13px; margin: 0; }
.main-actions { display: flex; gap: 12px; flex-wrap: wrap; }
@media (max-width: 860px) {
  .cards-row { grid-template-columns: 1fr; }
}
</style>
