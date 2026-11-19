<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, type GroupView, type BatchView } from '../api/client'

// 组与批次（04 §5.8）：目标组管理 + 批次记录；删除只清组织关系（服务端保证）。
const groups = ref<GroupView[]>([])
const batches = ref<BatchView[]>([])
const openGroup = ref<GroupView | null>(null)
const loading = ref(true)
const error = ref('')
const newName = ref('')
const renameValue = ref('')
const busy = ref(false)

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get<GroupView[]>('/api/v1/groups')
    groups.value = data
    if (openGroup.value) {
      const cur = data.find((g) => g.id === openGroup.value?.id)
      openGroup.value = cur ?? null
      if (cur) await loadBatches(cur)
    }
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

async function loadBatches(g: GroupView) {
  const { data } = await api.get<BatchView[]>(`/api/v1/groups/${g.id}/batches`)
  batches.value = data
}

function toggle(g: GroupView) {
  if (openGroup.value?.id === g.id) {
    openGroup.value = null
    return
  }
  openGroup.value = g
  loadBatches(g)
}

async function create() {
  if (!newName.value.trim() || busy.value) return
  busy.value = true
  try {
    await api.post('/api/v1/groups', { name: newName.value.trim() })
    newName.value = ''
    await load()
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    busy.value = false
  }
}

async function rename(g: GroupView) {
  const name = renameValue.value.trim()
  if (!name || name === g.name) return
  try {
    await api.patch(`/api/v1/groups/${g.id}`, { name })
    renameValue.value = ''
    await load()
  } catch (e) {
    error.value = (e as { message: string }).message
  }
}

async function archive(g: GroupView, archived: boolean) {
  try {
    await api.post(`/api/v1/groups/${g.id}/archive`, { archived })
    await load()
  } catch (e) {
    error.value = (e as { message: string }).message
  }
}

async function remove(g: GroupView) {
  const ok = confirm(
    `确定删除组「${g.name}」？\n影响：组内的单号和批次会变成“未分组”，` +
    '查询结果、批次历史和扣费记录都会保留，不会被删除。',
  )
  if (!ok) return
  try {
    await api.del(`/api/v1/groups/${g.id}`)
    if (openGroup.value?.id === g.id) openGroup.value = null
    await load()
  } catch (e) {
    error.value = (e as { message: string }).message
  }
}

function distText(g: GroupView): string {
  const d = g.status_distribution
  if (!Object.keys(d).length) return '—'
  return Object.entries(d)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${k} ${n}`)
    .join('，')
}

const BATCH_STATE: Record<string, string> = {
  accepted: '已受理', processing: '查询中', completed: '已完成', failed: '处理失败',
}

function fmt(t?: string): string {
  return t ? new Date(t).toLocaleString() : '—'
}
</script>

<template>
  <section>
    <h1 class="page-title">组与批次</h1>
    <p class="page-sub">
      目标组用来组织你的单号；每次提交会自动归入“默认组”。删除组只影响分组关系，
      查询结果与扣费记录不受影响。
    </p>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <div class="card new-group">
      <input v-model="newName" maxlength="50" placeholder="新组名称" @keyup.enter="create" />
      <button class="btn sm" :disabled="busy" @click="create">创建组</button>
    </div>

    <p v-if="!loading && groups.length === 0" class="hint" role="status">
      还没有分组。第一次提交后会自动创建“默认组”。
    </p>

    <div v-for="g in groups" :key="g.id" class="card group-card">
      <div class="group-head" @click="toggle(g)">
        <strong>{{ g.name }}</strong>
        <span v-if="g.is_default" class="badge">默认组</span>
        <span v-if="g.archived" class="badge muted">已归档</span>
        <span class="meta">{{ g.tracking_count }} 单号 · {{ g.batch_count }} 批次</span>
        <span class="meta">{{ g.archived ? '—' : distText(g) }}</span>
      </div>

      <div class="group-actions" @click.stop>
        <input v-model="renameValue" placeholder="改成新名称" maxlength="50" />
        <button class="btn sm ghost" @click="rename(g)">重命名</button>
        <button v-if="!g.archived" class="btn sm ghost" @click="archive(g, true)">归档</button>
        <button v-else class="btn sm ghost" @click="archive(g, false)">取消归档</button>
        <button class="btn sm danger" @click="remove(g)">删除组</button>
      </div>

      <div v-if="openGroup?.id === g.id" class="group-batches">
        <p v-if="batches.length === 0" class="hint">该组还没有批次记录。</p>
        <table v-else class="list">
          <thead>
            <tr><th>批次</th><th>状态</th><th>单号数</th><th>扣费</th><th>创建时间</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="b in batches" :key="b.id">
              <td class="mono">{{ b.id.slice(0, 8) }}…</td>
              <td>{{ BATCH_STATE[b.state] ?? b.state }}</td>
              <td>{{ b.total_count }}（有效 {{ b.valid_count }}）</td>
              <td>{{ b.points_charged }} 积分</td>
              <td>{{ fmt(b.created_at) }}</td>
              <td>
                <RouterLink :to="`/results?op=${b.id}`">查看结果</RouterLink>
                <RouterLink :to="`/exports?batch=${b.id}`">导出</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.new-group { display: flex; gap: 8px; }
.new-group input { flex: 1; max-width: 280px; }
.group-card { margin-top: 16px; }
.group-head { display: flex; align-items: center; gap: 10px; cursor: pointer; flex-wrap: wrap; }
.meta { color: var(--fg-soft); font-size: 13px; }
.group-actions { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.group-actions input { max-width: 200px; }
.group-batches { margin-top: 12px; }
.badge.muted { opacity: 0.6; }
.btn.danger { color: var(--danger, #b00); }
</style>
