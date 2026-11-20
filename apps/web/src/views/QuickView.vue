<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { api, type SubmissionAccepted, type TrackingView } from '../api/client'
import { loadSession, loadStatusDict, lang } from '../composables/session'
import { splitDraft, requestIdFor, clearRequestId, MAX_LINES } from '../logic/draft'
import StatusDistBar from '../components/StatusDistBar.vue'
import TrackingCard from '../components/TrackingCard.vue'

// 临时快查（04 §5.3；P15 直出结果）：提交受理后直接展示单号卡片与轨迹，
// 自动轮询刷新直到本批完结；不再经过"受理详情"中间页（对齐竞品体验）。
const text = ref('')
const submitting = ref(false)
const error = ref('')
const accepted = ref<SubmissionAccepted | null>(null)

const draft = computed(() => splitDraft(text.value))
const canSubmit = computed(
  () => !submitting.value && draft.value.totalLines > 0 && !draft.value.overLimit,
)

const items = ref<TrackingView[]>([])
const polling = ref(false)
const pollFatal = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | null = null

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

onUnmounted(stopPolling)
watch(lang, () => { if (accepted.value) void loadResults() })

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
    items.value = []
    clearRequestId() // 已产生操作，后续新提交用新键
    localStorage.removeItem('pt_quick_draft_text')
    await loadSession(true) // 余额以服务端为准刷新
    startPolling()
  } catch (e) {
    error.value = (e as { message: string }).message
    // 保留输入内容（04 §7.4），幂等键已存，重试自动复用
  } finally {
    submitting.value = false
  }
}

/** 直接拉取本批结果（batch_id = 操作 public_id），退避轮询到完结。 */
async function loadResults() {
  if (!accepted.value) return
  try {
    const { data } = await api.get<TrackingView[]>('/api/v1/trackings', {
      lang: lang.value || undefined,
    })
    items.value = data.filter((it) => it.batch_id === accepted.value!.operation_id)
    pollFatal.value = false
  } catch {
    /* 轮询失败静默，下轮再试 */
  }
}

function startPolling() {
  stopPolling()
  polling.value = true
  let delay = 2500
  const tick = async () => {
    if (!accepted.value) { stopPolling(); return }
    await loadResults()
    const done = items.value.length > 0 && items.value.every((it) => it.is_terminal)
    if (done) { polling.value = false; return }
    pollTimer = setTimeout(tick, delay)
    delay = Math.min(delay * 1.5, 20000)
  }
  pollTimer = setTimeout(tick, delay)
}

function stopPolling() {
  polling.value = false
  pollFatal.value = false
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

const terminalCount = computed(() => items.value.filter((it) => it.is_terminal).length)
const dist = computed(() => {
  const d: Record<string, number> = {}
  for (const it of items.value) {
    const k = it.status_key || 'other'
    d[k] = (d[k] ?? 0) + 1
  }
  return d
})

const stateText = computed(() => {
  if (items.value.length === 0) return '正在查询，结果会逐步更新…'
  if (polling.value) return `查询中 — 已完结 ${terminalCount.value} / ${items.value.length}`
  return `已完结 ${terminalCount.value} / ${items.value.length}`
})

function reset() {
  stopPolling()
  accepted.value = null
  items.value = []
  text.value = ''
}
</script>

<template>
  <section>
    <h1 class="page-title">临时快查</h1>
    <p class="page-sub">少量单号的快速路径；提交后直接在这里看到结果，不必跳转。</p>

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
      </div>
      <p class="hint">点击「开始查询」即提交并按规则扣费。</p>
    </div>

    <!-- 直出结果（P15）：受理摘要收进折叠，主视图就是单号卡片 -->
    <template v-else>
      <div class="card summary">
        <p class="ok-box" role="status">
          已受理 — 扣费 {{ accepted.points_charged }} 积分
          （可计费 {{ accepted.valid_count }} · 免扣 {{ accepted.free_count }} · 无效 {{ accepted.invalid_count }}）；
          关闭页面不会取消任务。
        </p>
        <details v-if="accepted.invalid_items.length">
          <summary class="hint">不可计费明细（{{ accepted.invalid_items.length }} 条）</summary>
          <ul class="invalid-list">
            <li v-for="it in accepted.invalid_items" :key="it.line_no">
              第 {{ it.line_no }} 行：<span class="mono">{{ it.raw }}</span>（原因：{{ it.reason }}）
            </li>
          </ul>
        </details>
        <p class="progress" role="status">
          <span v-if="polling" class="spinner" aria-hidden="true"></span>{{ stateText }}
        </p>
        <StatusDistBar :distribution="dist" :total="items.length" />
        <div class="actions">
          <button class="btn ghost sm" @click="reset">继续提交</button>
          <RouterLink class="btn ghost sm" :to="`/results/batch/${accepted.operation_id}`">在批次页查看</RouterLink>
        </div>
      </div>

      <div v-if="items.length === 0" class="card empty-state" role="status">
        <p>正在等待查询结果…（通常几秒内陆续到达）</p>
      </div>
      <div v-else class="cards">
        <TrackingCard v-for="it in items" :key="it.id" :item="it" />
      </div>
    </template>
  </section>
</template>

<style scoped>
.field-label { display: block; font-weight: 600; margin-bottom: 8px; }
.fee-rule { font-weight: 500; }
.actions { display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
.invalid-list { font-size: 13px; color: var(--fg-soft); }
.progress { display: flex; align-items: center; gap: 8px; font-weight: 500; margin: 4px 0; }
.spinner {
  width: 14px; height: 14px; border-radius: 999px; flex: none;
  border: 2px solid var(--line); border-top-color: var(--brand);
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.cards { margin-top: 8px; }
</style>
