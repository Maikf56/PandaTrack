<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api, type TrackingView, type CheckUpdateResult } from '../api/client'
import { loadStatusDict, session, statusLabel } from '../composables/session'

// 结果列表（04 §5.6）：长期查看与筛选主页面。
const route = useRoute()
const items = ref<TrackingView[]>([])
const loading = ref(true)
const error = ref('')
const search = ref('')
const filterStatus = ref('')
const selected = ref<Set<string>>(new Set())
const checking = ref(false)
const checkFeedback = ref('')

const opFilter = computed(() =>
  typeof route.query.op === 'string' ? route.query.op : undefined,
)
// opFilter 预留：批次过滤接口开放后接入（04 §5.6）
void opFilter

onMounted(async () => {
  await loadStatusDict()
  await reload()
})

async function reload() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get<TrackingView[]>('/api/v1/trackings')
    items.value = data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

const filtered = computed(() =>
  items.value.filter((it) => {
    if (search.value && !it.normalized_number.includes(search.value.trim())) return false
    if (filterStatus.value && it.status_key !== filterStatus.value) return false
    return true
  }),
)

function toggle(id: string) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

/** 检查更新（04 §6.3）：只表达希望检查；沿用旧结果时明确显示。 */
async function checkUpdates() {
  if (selected.value.size === 0 || checking.value) return
  checking.value = true
  checkFeedback.value = ''
  try {
    const { data } = await api.post<CheckUpdateResult[]>('/api/v1/check-updates', {
      customer_tracking_ids: [...selected.value],
    })
    const fresh = data.filter((r) => r.fresh).length
    const willFetch = data.filter((r) => r.will_fetch).length
    checkFeedback.value =
      `已提交检查：${data.length} 项；其中 ${fresh} 项将沿用现有结果，` +
      `${willFetch} 项已创建检查任务。结果在后台更新，稍后查看。`
  } catch (e) {
    checkFeedback.value = ''
    error.value = (e as { message: string }).message
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <section>
    <h1 class="page-title">结果列表</h1>
    <p class="page-sub">按状态、单号筛选你的查询结果；结果由服务端按当前身份过滤。</p>

    <div class="card filters">
      <label for="fl-search">单号搜索</label>
      <input id="fl-search" v-model="search" placeholder="输入单号片段" />
      <label for="fl-status">状态</label>
      <select id="fl-status" v-model="filterStatus">
        <option value="">全部状态</option>
        <option v-for="s in session.statusDict?.statuses ?? []" :key="s.key" :value="s.key">
          {{ s.label_zh }}{{ s.terminal ? '（终态）' : '' }}
        </option>
      </select>
    </div>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>
    <p v-else-if="filtered.length === 0" class="hint" role="status">
      还没有查询记录。先粘贴 USPS 单号开始查询，提交后这里会显示结果。
    </p>

    <table v-else class="list">
      <thead>
        <tr>
          <th>选择</th>
          <th>单号</th>
          <th>当前状态</th>
          <th>取得时间</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="it in filtered" :key="it.id">
          <td>
            <input
              type="checkbox"
              :checked="selected.has(it.id)"
              :aria-label="`选择 ${it.normalized_number}`"
              @change="toggle(it.id)"
            />
          </td>
          <td class="mono">{{ it.normalized_number }}</td>
          <td>
            <span class="badge" :class="{ terminal: it.is_terminal }">{{ it.label_zh || statusLabel(it.status_key) }}</span>
          </td>
          <td>{{ it.last_success_at ? new Date(it.last_success_at).toLocaleString() : '暂未获取' }}</td>
          <td>
            <RouterLink :to="`/results/${it.id}`">查看详情</RouterLink>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="card bulk" v-if="selected.size > 0">
      <p class="hint">已选择 {{ selected.size }} 项</p>
      <p v-if="checkFeedback" class="ok-box" role="status">{{ checkFeedback }}</p>
      <button class="btn" :disabled="checking" @click="checkUpdates">
        {{ checking ? '提交检查中…' : '检查更新' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.filters { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }
.filters label { display: block; font-size: 13px; color: var(--fg-soft); margin-bottom: 4px; }
.filters input, .filters select { width: auto; min-width: 180px; }
.bulk { border-left: 4px solid var(--brand); }
</style>
