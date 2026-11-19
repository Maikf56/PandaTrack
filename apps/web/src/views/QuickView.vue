<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, type SubmissionAccepted } from '../api/client'
import { loadSession, loadStatusDict } from '../composables/session'
import { splitDraft, requestIdFor, clearRequestId, MAX_LINES } from '../logic/draft'

// 临时快查（04 §5.3）：仍走正式提交接口；点击开始查询即提交并可能扣费。
const text = ref('')
const submitting = ref(false)
const error = ref('')
const accepted = ref<SubmissionAccepted | null>(null)
const pollTimer = ref<ReturnType<typeof setInterval> | null>(null)
const opProgress = ref<{ state: string; done: number; total: number } | null>(null)

const draft = computed(() => splitDraft(text.value))
const canSubmit = computed(
  () => !submitting.value && draft.value.totalLines > 0 && !draft.value.overLimit,
)

onMounted(async () => {
  await Promise.all([loadSession(true), loadStatusDict()])
  // 首页带过来的草稿（04 验收用例 1）
  const carried = sessionStorage.getItem('pt_quick_draft_text')
  if (carried) {
    text.value = carried
    sessionStorage.removeItem('pt_quick_draft_text')
  } else {
    text.value = localStorage.getItem('pt_quick_draft_text') ?? ''
  }
})

function clearAll() {
  text.value = ''
  localStorage.removeItem('pt_quick_draft_text')
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = ''
  accepted.value = null
  const lines = draft.value.lines
  try {
    const { data } = await api.post<SubmissionAccepted>('/api/v1/submissions', {
      source: 'paste',
      client_request_id: requestIdFor(lines),
      lines,
    })
    accepted.value = data
    clearRequestId() // 已产生操作，后续新提交用新键
    localStorage.removeItem('pt_quick_draft_text')
    await loadSession(true) // 余额以服务端为准刷新
    startPolling(data.operation_id)
  } catch (e) {
    error.value = (e as { message: string }).message
    // 保留输入内容（04 §7.4），幂等键已存，重试自动复用
  } finally {
    submitting.value = false
  }
}

/** 退避只读轮询进度（04 §8.2：轮询不新建任务/不扣费）。 */
function startPolling(operationId: string) {
  stopPolling()
  opProgress.value = null
  let delay = 3000
  const tick = async () => {
    try {
      const { data } = await api.get<{
        id: string; state: string; total_count: number; valid_count: number
      }>(`/api/v1/operations/${operationId}`)
      opProgress.value = {
        state: data.state,
        done: data.valid_count,
        total: data.total_count,
      }
      if (data.state === 'completed') {
        stopPolling()
        return
      }
    } catch {
      /* 轮询失败静默，下轮再试；不弹窗 */
    }
    pollTimer.value = setTimeout(tick, delay)
    delay = Math.min(delay * 1.5, 30000)
  }
  pollTimer.value = setTimeout(tick, delay)
}

function stopPolling() {
  if (pollTimer.value) {
    clearTimeout(pollTimer.value)
    pollTimer.value = null
  }
}

const stateText = computed(() => {
  if (!opProgress.value) return ''
  const s = opProgress.value.state
  if (s === 'completed') return '已完成'
  if (s === 'failed') return '处理失败，请联系支持'
  return '正在查询，结果会逐步更新'
})
</script>

<template>
  <section>
    <h1 class="page-title">临时快查</h1>
    <p class="page-sub">少量单号的快速路径；仍走正式提交接口，结果进入可回溯的操作记录。</p>

    <div v-if="!accepted" class="card">
      <label for="quick-input" class="field-label">输入 USPS 单号（每行一个）</label>
      <textarea
        id="quick-input"
        v-model="text"
        class="big mono"
        placeholder="每行一个单号，最多 35 行"
      ></textarea>
      <p class="hint" role="status">
        已接收 {{ draft.totalLines }} 行 / 上限 {{ MAX_LINES }} 行
        <template v-if="draft.overLong.length">；第 {{ draft.overLong.join('、') }} 行超过 100 字符</template>
      </p>
      <p v-if="draft.overLimit" class="error-box" role="alert">
        超过 {{ MAX_LINES }} 行，请删减后重试或拆分为多次提交
      </p>
      <p class="hint fee-rule">费用规则：1 个新单号扣 1 积分，30 天内重复免扣，无效项不扣费。</p>
      <p v-if="error" class="error-box" role="alert">{{ error }}</p>
      <div class="actions">
        <button class="btn" :disabled="!canSubmit" @click="submit">
          {{ submitting ? '提交中…' : '开始查询' }}
        </button>
        <button class="btn ghost" @click="clearAll">清空</button>
        <RouterLink class="btn ghost" to="/dashboard">返回工作台</RouterLink>
      </div>
      <p class="hint">点击「开始查询」即提交并按规则扣费。</p>
    </div>

    <!-- 受理卡（04 §5.4 第二步）：只显示服务端返回的实际结果 -->
    <div v-else class="card accepted">
      <p class="ok-box" role="status">已受理 — 查询结果将在后台逐步更新；关闭页面不会取消任务。</p>
      <h3>本次受理</h3>
      <ul class="kv">
        <li><span>操作 ID</span><span class="mono">{{ accepted.operation_id }}</span></li>
        <li><span>总条数</span><span>{{ accepted.total_count }}</span></li>
        <li><span>可计费</span><span>{{ accepted.valid_count }}</span></li>
        <li><span>免扣（30 天重复）</span><span>{{ accepted.free_count }}</span></li>
        <li><span>不可计费</span><span>{{ accepted.invalid_count }}</span></li>
        <li><span>本次实际扣费</span><span>{{ accepted.points_charged }} 积分</span></li>
      </ul>
      <details v-if="accepted.invalid_items.length">
        <summary class="hint">查看不可计费明细（{{ accepted.invalid_items.length }} 条）</summary>
        <ul class="invalid-list">
          <li v-for="it in accepted.invalid_items" :key="it.line_no">
            第 {{ it.line_no }} 行：<span class="mono">{{ it.raw }}</span>（原因：{{ it.reason }}）
          </li>
        </ul>
      </details>
      <div v-if="opProgress" class="progress-block" role="status">
        <p>{{ stateText }}</p>
        <p v-if="opProgress.total > 0" class="hint">
          已获取结果 {{ opProgress.done }} / {{ opProgress.total }}
        </p>
      </div>
      <div class="actions">
        <RouterLink class="btn" :to="`/results?op=${accepted.operation_id}`">查看结果</RouterLink>
        <button
          class="btn ghost"
          @click="stopPolling(); accepted = null; opProgress = null"
        >继续提交</button>
        <RouterLink class="btn ghost" to="/dashboard">返回工作台</RouterLink>
      </div>
    </div>
  </section>
</template>

<style scoped>
.field-label { display: block; font-weight: 600; margin-bottom: 8px; }
.fee-rule { font-weight: 500; }
.actions { display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
.kv { list-style: none; padding: 0; margin: 12px 0; }
.kv li { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--line); }
.invalid-list { font-size: 13px; color: var(--fg-soft); }
.progress-block { margin-top: 12px; }
</style>
