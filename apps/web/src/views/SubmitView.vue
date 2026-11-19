<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { api, type SubmissionAccepted, type SubmissionEstimate, type ImportAccepted, type GroupView } from '../api/client'
import { loadSession, loadStatusDict } from '../composables/session'
import { splitDraft, requestIdFor, clearRequestId } from '../logic/draft'

// 提交单号（04 §5.4，G2 流程 1）：两步「输入与规则说明 → 受理结果」。
// 无预览/报价步骤；实时解析面板是输入辅助，最终以 202 受理结果为唯一权威。
const text = ref('')
const fileName = ref<string | null>(null)
const submitting = ref(false)
const estimating = ref(false)
const error = ref('')
const accepted = ref<(SubmissionAccepted | ImportAccepted) | null>(null)
const acceptedKind = ref<'paste' | 'import'>('paste')

// 目标组（默认组自动归入；非默认组触发防呆确认）
const groups = ref<GroupView[]>([])
const targetGroupId = ref('')

const draft = computed(() => splitDraft(text.value))
const isBatch = computed(() => draft.value.totalLines > 35)
const MAX_IMPORT_LINES = 100_000 // 契约 ImportCreate.lines 上限
const overImportLimit = computed(() => draft.value.totalLines > MAX_IMPORT_LINES)

const estimate = ref<SubmissionEstimate | null>(null)
const estimateError = ref('')

// 目标组与防呆确认（04 §5.4：>1000 条或非默认组先确认；不产生报价、不入账）
const pendingSubmit = ref(false)
const defaultGroup = computed(() => groups.value.find((g) => g.is_default))
const selectedGroup = computed(() =>
  groups.value.find((g) => g.id === targetGroupId.value) ?? defaultGroup.value,
)
const isNonDefault = computed(() =>
  selectedGroup.value != null && !selectedGroup.value.is_default,
)
const needConfirm = computed(() => isNonDefault.value || draft.value.totalLines > 1000)

const resultReasonZh: Record<string, string> = {
  empty: '空行',
  too_long: '内容过长',
  bad_chars: '包含无法安全识别的字符',
  bad_format: '暂不支持的格式',
  duplicate_in_request: '重复输入',
}

onMounted(async () => {
  await Promise.all([loadSession(true), loadStatusDict()])
  try {
    const { data } = await api.get<GroupView[]>('/api/v1/groups')
    groups.value = data
    const def = data.find((g) => g.is_default)
    if (def) targetGroupId.value = def.id
  } catch {
    /* 组列表加载失败不阻断输入；提交时目标组留空走默认组 */
  }
})

// 实时解析面板：输入即算，防抖 300ms 调服务端预估接口（04 §5.4）
// 竞态守卫：只采纳最后一次请求的响应（连续输入时旧响应可能后到）。
let estimateTimer: ReturnType<typeof setTimeout> | null = null
let estimateSeq = 0
watch(text, () => {
  accepted.value = null
  error.value = ''
  if (estimateTimer) clearTimeout(estimateTimer)
  if (draft.value.totalLines === 0) {
    estimate.value = null
    estimateError.value = ''
    return
  }
  estimateTimer = setTimeout(runEstimate, 300)
})

async function runEstimate() {
  const seq = ++estimateSeq
  estimating.value = true
  estimateError.value = ''
  try {
    const { data } = await api.post<SubmissionEstimate>('/api/v1/submissions/estimate', {
      lines: draft.value.lines.slice(0, MAX_IMPORT_LINES),
    })
    if (seq === estimateSeq) estimate.value = data
  } catch (e) {
    estimate.value = null
    estimateError.value = (e as { message: string }).message
  } finally {
    estimating.value = false
  }
}

// 文件导入：客户端读取为行文本，保护 ≤64MB，不做格式判定
const fileInput = ref<HTMLInputElement | null>(null)
async function onFileChange(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 64 * 1024 * 1024) {
    error.value = '文件超过 64 MB 上限，请拆分后分批上传'
    return
  }
  const content = await file.text()
  text.value = content
  fileName.value = file.name
}
function removeFile() {
  text.value = ''
  fileName.value = null
  if (fileInput.value) fileInput.value.value = ''
}

// 预估接口失败不阻断提交（受理不依赖预估；服务端才是计费权威），
// 但预估已判余额不足时必须禁用（防呆，避免注定失败的 409 请求）。
const estimateBlocked = computed(() => estimate.value != null && estimate.value.insufficient)
const canSubmit = computed(() =>
  !submitting.value &&
  draft.value.totalLines > 0 &&
  !overImportLimit.value &&
  !draft.value.overLong.length &&
  !estimateBlocked.value,
)
const insufficientGap = computed(() =>
  estimate.value ? estimate.value.points_estimate - estimate.value.balance : 0,
)

function onSubmitClick() {
  if (!canSubmit.value) return
  if (needConfirm.value) {
    pendingSubmit.value = true // 防呆确认卡（§5.4）：目标组/条数/预估积分
    return
  }
  void doSubmit()
}

async function doSubmit() {
  pendingSubmit.value = false
  submitting.value = true
  error.value = ''
  accepted.value = null
  const lines = draft.value.lines
  const group = selectedGroup.value
  try {
    if (isBatch.value) {
      const { data } = await api.post<ImportAccepted>('/api/v1/imports', {
        file_name: fileName.value,
        client_request_id: requestIdFor(lines),
        lines,
        target_group_name: group && !group.is_default ? group.name : undefined,
      })
      acceptedKind.value = 'import'
      accepted.value = data
    } else {
      const { data } = await api.post<SubmissionAccepted>('/api/v1/submissions', {
        source: 'paste',
        client_request_id: requestIdFor(lines),
        lines,
        target_group_name: group && !group.is_default ? group.name : undefined,
      })
      acceptedKind.value = 'paste'
      accepted.value = data
    }
    clearRequestId() // 已产生操作，后续新提交用新键
    await loadSession(true) // 余额以服务端刷新为准
  } catch (e) {
    error.value = (e as { message: string }).message
    // 保留输入内容（04 §7.4）；幂等键已存，重试自动复用
  } finally {
    submitting.value = false
  }
}

function copyInvalid() {
  const items = estimate.value?.invalid_items ?? []
  const text2 = items.map((it) => `${it.line_no}: ${it.raw} (${resultReasonZh[it.reason] ?? it.reason})`).join('\n')
  void navigator.clipboard?.writeText(text2)
}
</script>

<template>
  <section>
    <h1 class="page-title">提交单号</h1>
    <p class="page-sub">粘贴或上传单号，服务端一次完成清洗、计费与受理；大批量自动进入导入任务。</p>

    <!-- 受理卡（04 §5.4 第二步）：只显示服务端返回的实际结果 -->
    <div v-if="accepted" class="card accepted">
      <p class="ok-box" role="status">已受理 — 查询结果将在后台逐步更新；关闭页面不会取消任务。</p>
      <h3>本次受理</h3>
      <ul class="kv">
        <li>
          <span>{{ acceptedKind === 'import' ? '导入任务 ID' : '操作 ID' }}</span>
          <span class="mono">{{ acceptedKind === 'import' ? (accepted as ImportAccepted).import_job_id : (accepted as SubmissionAccepted).operation_id }}</span>
        </li>
        <li><span>总条数</span><span class="mono">{{ accepted.total_count }}</span></li>
        <li><span>可计费</span><span class="mono">{{ accepted.valid_count }}</span></li>
        <li><span>免扣（30 天重复）</span><span class="mono">{{ accepted.free_count }}</span></li>
        <li><span>不可计费</span><span class="mono">{{ accepted.invalid_count }}</span></li>
        <li><span>本次实际扣费</span><span class="mono">{{ accepted.points_charged }} 积分</span></li>
      </ul>
      <p class="hint">本次提交已自动归入默认组；结果可在结果列表、组与批次中找回。</p>
      <div class="actions">
        <RouterLink class="btn" :to="acceptedKind === 'import' ? '/imports' : '/results'">查看进度</RouterLink>
        <RouterLink v-if="acceptedKind === 'import'" class="btn ghost" to="/imports">查看导入任务</RouterLink>
        <button class="btn ghost" @click="accepted = null; text = ''; fileName = null; estimate = null">继续提交</button>
        <RouterLink class="btn ghost" to="/dashboard">返回工作台</RouterLink>
      </div>
    </div>

    <template v-else>
      <div class="card">
        <label for="submit-input" class="field-label">输入 USPS 单号（每行一个，或上传文件）</label>
        <textarea
          id="submit-input"
          v-model="text"
          class="big mono"
          placeholder="9400 1000 0000 0000 0000 00&#10;每行一个单号；≤35 行即时受理，更大批量自动进入导入任务"
          :disabled="fileName !== null"
        ></textarea>
        <div class="file-row">
          <label class="file-btn">
            <input ref="fileInput" type="file" accept=".txt,.csv,text/plain" @change="onFileChange" />
            上传文件（≤64 MB）
          </label>
          <span v-if="fileName" class="hint file-chip">
            {{ fileName }}
            <button class="linklike" @click="removeFile">移除</button>
          </span>
          <span v-else class="hint">或直接在上方粘贴批量文本</span>
        </div>

        <p class="hint" role="status">
          已接收 {{ draft.totalLines }} 行
          <template v-if="draft.overLong.length">；第 {{ draft.overLong.join('、') }} 行超过 100 字符</template>
          <template v-if="isBatch">；将走导入任务路径（结果在导入任务页查看进度）</template>
        </p>
        <p v-if="overImportLimit" class="error-box" role="alert">
          超过单次 {{ MAX_IMPORT_LINES.toLocaleString() }} 行上限，请拆分后分批提交
        </p>

        <!-- 目标组选择 -->
        <div v-if="groups.length" class="group-row">
          <label for="target-group" class="field-label">目标组</label>
          <select id="target-group" v-model="targetGroupId">
            <option v-for="g in groups" :key="g.id" :value="g.id">
              {{ g.name }}{{ g.is_default ? '（默认组）' : '' }} · {{ g.tracking_count }} 单
            </option>
          </select>
        </div>

        <!-- 实时解析面板（服务端预估接口；输入辅助，非预览步骤） -->
        <div v-if="estimate || estimating || estimateError" class="estimate-panel" aria-live="polite">
          <template v-if="estimating">正在解析…</template>
          <template v-else-if="estimateError">
            <p class="hint">{{ estimateError }}（预估不可用不影响提交，以受理结果为准）</p>
          </template>
          <template v-else-if="estimate">
            <div class="estimate-stats">
              <span>总行数 <strong class="mono">{{ estimate.total_count }}</strong></span>
              <span>可计费 <strong class="mono">{{ estimate.billable_count }}</strong></span>
              <span>30 天内免扣 <strong class="mono">{{ estimate.free_count }}</strong></span>
              <span>识别失败 <strong class="mono">{{ estimate.invalid_items.length > 0 ? estimate.invalid_items.length + '+' : estimate.invalid_items.length }}</strong></span>
            </div>
            <details v-if="estimate.invalid_items.length">
              <summary class="hint">识别失败明细（{{ estimate.invalid_items.length }} 条）</summary>
              <ul class="invalid-list">
                <li v-for="it in estimate.invalid_items" :key="it.line_no">
                  第 {{ it.line_no }} 行：<span class="mono">{{ it.raw }}</span>（{{ resultReasonZh[it.reason] ?? it.reason }}）
                </li>
              </ul>
              <button class="btn ghost sm" @click="copyInvalid">复制失败清单</button>
            </details>
          </template>
        </div>

        <p v-if="error" class="error-box" role="alert">{{ error }}</p>

        <!-- 成本预估条（固定在主按钮旁；常驻标注「预估，以提交结果为准」） -->
        <div class="cost-bar">
          <div class="cost-text" role="status">
            <template v-if="estimate">
              将新增 <strong class="mono">{{ estimate.billable_count }}</strong> 单 ·
              预估消耗 <strong class="mono">{{ estimate.points_estimate }}</strong> 积分 ·
              其中 <strong class="mono">{{ estimate.free_count }}</strong> 单 30 天内免扣
              <span class="hint">（当前余额 <span class="mono">{{ estimate.balance }}</span>）</span>
              <span v-if="estimate.insufficient" class="insufficient">
                余额不足，还差 <strong class="mono">{{ insufficientGap }}</strong> 积分
              </span>
            </template>
            <template v-else>输入单号后自动显示预估</template>
          </div>
          <div class="actions">
            <button class="btn" :disabled="!canSubmit" @click="onSubmitClick">
              {{ submitting ? '提交中…' : '开始查询' }}
            </button>
            <button
              v-if="draft.totalLines > 0"
              class="btn ghost"
              @click="text = ''; fileName = null; estimate = null"
            >清空</button>
          </div>
          <p class="hint">点击「开始查询」即提交并按规则扣费。费用规则：1 个新单号扣 1 积分，30 天内重复免扣，无效项不扣费；单次上限 1,000,000 条。预估仅供参考，以提交结果为准。</p>
        </div>
      </div>

      <!-- 防呆确认卡（04 §5.4）：大批量或非默认组；确认后仍走正常提交，不入账 -->
      <div v-if="pendingSubmit" class="modal-mask" @click.self="pendingSubmit = false">
        <div class="modal card" role="dialog" aria-modal="true" aria-label="提交确认">
          <h3>确认提交</h3>
          <ul class="kv">
            <li><span>目标组</span><strong>{{ selectedGroup?.name ?? '默认组' }}</strong></li>
            <li><span>条数</span><strong class="mono">{{ draft.totalLines }}</strong></li>
            <li><span>预估积分</span><strong class="mono">{{ estimate?.points_estimate ?? '—' }}</strong></li>
          </ul>
          <p class="hint">本次提交为{{ isNonDefault ? '非默认目标组' : '大批量' }}提交，请核对以上信息。确认后立即按规则扣费。</p>
          <div class="actions">
            <button class="btn" @click="doSubmit">确认提交</button>
            <button class="btn ghost" @click="pendingSubmit = false">再看看</button>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.actions { display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
.file-row { display: flex; align-items: center; gap: 12px; margin: 10px 0; flex-wrap: wrap; }
.file-btn {
  display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
  border: 1px dashed var(--line); border-radius: var(--radius-ctl);
  padding: 8px 14px; color: var(--fg-soft); font-size: 14px;
  transition: border-color var(--dur) ease-out, color var(--dur) ease-out;
}
.file-btn:hover { border-color: var(--brand); color: var(--brand); }
.file-btn input[type='file'] { display: none; }
.file-chip { display: inline-flex; align-items: center; gap: 8px; }
.group-row { margin-top: 12px; }
.group-row select { max-width: 360px; }
.estimate-panel {
  margin-top: 14px; padding: 12px 14px; border: 1px solid var(--line);
  border-radius: var(--radius-ctl); background: var(--bg); font-size: 14px;
}
.estimate-stats { display: flex; gap: 20px; flex-wrap: wrap; }
.estimate-stats strong { font-weight: 700; }
.invalid-list { font-size: 13px; color: var(--fg-soft); margin: 8px 0; padding-left: 18px; }
.cost-bar {
  margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line);
}
.cost-text { font-size: 14px; }
.insufficient { color: var(--err); font-weight: 600; margin-left: 8px; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(28, 25, 23, 0.4);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal { width: min(440px, 92vw); margin: 0; box-shadow: var(--shadow-2); }
</style>
