<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { api, type RunLogRow, type AttemptRow } from '../api/client'

// 系统运行日志：worker 每轮 cycle 的查询进度（领取/成功/重试/死信）与结果
// （事实/事件落库、最近采集明细）。数据源 A 库 run_log（a/0003）+ fetch_attempt_log。
const items = ref<RunLogRow[]>([])
const attempts = ref<AttemptRow[]>([])
const total = ref(0)
const loading = ref(true)
const error = ref('')
const levelFilter = ref('')
const auto = ref(true)
const expanded = ref<Set<number>>(new Set())
let timer: number | undefined

const LEVEL_ZH: Record<string, string> = { info: '正常', warn: '警告', error: '错误' }
const KIND_ZH: Record<string, string> = {
  cycle: '调度轮次',
  tick_error: '轮次异常',
  canary_halt: '金丝雀拦截',
}

const STATE_ZH: Record<string, string> = {
  succeeded: '成功',
  pending: '待执行',
  claimed: '已领取',
  running: '执行中',
  retry_scheduled: '待重试',
  dead_letter: '死信',
}

onMounted(() => {
  reload()
  schedule()
})

onUnmounted(() => window.clearInterval(timer))

function schedule() {
  window.clearInterval(timer)
  if (auto.value) timer = window.setInterval(reload, 10000)
}

function toggleAuto() {
  schedule()
  if (auto.value) reload()
}

async function reload() {
  error.value = ''
  try {
    const data = await api.get<{ items: RunLogRow[]; total: number }>(
      '/api/v1/admin/runlog',
      { limit: 100, level: levelFilter.value || undefined },
    )
    items.value = data.items
    total.value = data.total
    const at = await api.get<{ items: AttemptRow[] }>(
      '/api/v1/admin/runlog/attempts', { limit: 30 },
    )
    attempts.value = at.items
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

function toggleExpand(id: number) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function fmtSummary(s: Record<string, unknown> | null): string {
  if (!s || !Object.keys(s).length) return '—'
  return Object.entries(s).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join('\n')
}
</script>

<template>
  <section>
    <h1 class="page-title">系统运行日志</h1>
    <p class="page-sub">worker 每轮调度的查询进度（领取/成功/重试/死信）与结果（事实落库、采集明细）；每 10 秒自动刷新。</p>

    <div class="card form-row">
      <div>
        <label for="runlog-level" class="field-label">按级别过滤</label>
        <select id="runlog-level" v-model="levelFilter" @change="reload">
          <option value="">全部</option>
          <option value="info">正常</option>
          <option value="warn">警告</option>
          <option value="error">错误</option>
        </select>
      </div>
      <div style="flex:0">
        <label class="field-label">自动刷新</label>
        <button class="btn ghost sm" :class="{ ok: auto }" @click="toggleAuto">
          {{ auto ? '自动刷新中（10s）' : '已暂停，点击开启' }}
        </button>
      </div>
      <p class="hint" style="align-self: end">共 {{ total }} 轮</p>
      <p class="hint" style="align-self: end">
        <button class="btn ghost sm" @click="reload">手动刷新</button>
      </p>
    </div>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">正在加载…</p>

    <template v-else>
      <table v-if="items.length" class="list">
        <thead>
          <tr>
            <th>时间</th>
            <th>级别</th>
            <th>worker</th>
            <th>轮次</th>
            <th>领取</th>
            <th>成功</th>
            <th>重试</th>
            <th>死信</th>
            <th>事实/事件</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.run_log_id">
            <td>{{ new Date(row.created_at).toLocaleString() }}</td>
            <td>
              <span class="badge" :class="{ ok: row.level === 'info', warn: row.level === 'warn', err: row.level === 'error' }">
                {{ LEVEL_ZH[row.level] ?? row.level }}
              </span>
            </td>
            <td class="mono">{{ row.worker_id }}</td>
            <td>
              {{ KIND_ZH[row.kind] ?? row.kind }}
              <span v-if="row.cycle" class="hint">#{{ row.cycle }}</span>
              <span v-if="row.error_class" class="mono err-text"> {{ row.error_class }}</span>
            </td>
            <td class="mono">{{ row.claimed }}</td>
            <td class="mono">{{ row.succeeded }}</td>
            <td class="mono" :class="{ warnText: row.retried > 0 }">{{ row.retried }}</td>
            <td class="mono" :class="{ errText: row.dead_lettered > 0 }">{{ row.dead_lettered }}</td>
            <td class="mono">{{ row.facts_written }}/{{ row.events_written }}</td>
            <td>
              <button
                v-if="row.summary && Object.keys(row.summary).length"
                class="btn ghost sm"
                @click="toggleExpand(row.run_log_id)"
              >
                {{ expanded.has(row.run_log_id) ? '收起' : '展开' }}
              </button>
              <span v-else class="hint">—</span>
              <pre v-if="expanded.has(row.run_log_id)" class="detail-pre">{{ fmtSummary(row.summary) }}</pre>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="card"><p class="hint" role="status">暂无运行日志——worker 尚未产生采集活动（空转轮次不记录）。</p></div>

      <h2 class="section-title">最近采集明细</h2>
      <table v-if="attempts.length" class="list">
        <thead>
          <tr>
            <th>时间</th>
            <th>单号</th>
            <th>Provider</th>
            <th>任务状态</th>
            <th>尝试</th>
            <th>错误类别</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in attempts" :key="a.attempt_id">
            <td>{{ new Date(a.created_at).toLocaleString() }}</td>
            <td class="mono">{{ a.number }}</td>
            <td class="mono">{{ a.provider_code }}</td>
            <td>
              <span class="badge" :class="{ ok: a.state === 'succeeded', warn: a.state === 'retry_scheduled' || a.state === 'pending' || a.state === 'claimed' || a.state === 'running', err: a.state === 'dead_letter' }">
                {{ STATE_ZH[a.state] ?? a.state }}
              </span>
            </td>
            <td class="mono">{{ a.attempt }}</td>
            <td class="mono">{{ a.error_class ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="card"><p class="hint" role="status">暂无采集明细。</p></div>
    </template>
  </section>
</template>

<style scoped>
.section-title { font-size: 17px; margin: 24px 0 12px; }
.detail-pre {
  margin: 8px 0 0; padding: 10px 12px; background: var(--bg);
  border: 1px solid var(--line); border-radius: var(--radius-ctl);
  white-space: pre-wrap; word-break: break-all; font-size: 12px;
  font-family: var(--mono); max-width: 420px;
}
.err-text { color: var(--err); font-size: 12px; }
.warnText { color: var(--warn); }
.errText { color: var(--err); font-weight: 600; }
.btn.ghost.ok { color: var(--ok); border-color: var(--ok); }
</style>
