<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, type SubmissionAccepted, type SubmissionEstimate, type ImportAccepted, type GroupView } from '../api/client'
import { loadSession, loadStatusDict } from '../composables/session'
import { t } from '../i18n'
import { splitDraft, requestIdFor, clearRequestId } from '../logic/draft'

// 提交单号（04 §5.4，G2 流程 1）：两步「输入与规则说明 → 受理结果」。
// 无预览/报价步骤；实时解析面板是输入辅助，最终以 202 受理结果为唯一权威。
// P17：受理成功后直接跳转「我的查询」第三级批次页（客户要的是结果）。
const router = useRouter()
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

/* 失败原因文案：submit.reason.* 词典；未知原因码原样显示 */
function reasonText(reason: string): string {
  const key = `submit.reason.${reason}`
  return t(key) === key ? reason : t(key)
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
    error.value = t('submit.file_too_big')
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
    let opId: string | undefined
    if (isBatch.value) {
      const { data } = await api.post<ImportAccepted>('/api/v1/imports', {
        file_name: fileName.value,
        client_request_id: requestIdFor(lines),
        lines,
        target_group_name: group && !group.is_default ? group.name : undefined,
      })
      acceptedKind.value = 'import'
      accepted.value = data
      opId = (data as { operation_id?: string }).operation_id
    } else {
      const { data } = await api.post<SubmissionAccepted>('/api/v1/submissions', {
        source: 'paste',
        client_request_id: requestIdFor(lines),
        lines,
        target_group_name: group && !group.is_default ? group.name : undefined,
      })
      acceptedKind.value = 'paste'
      accepted.value = data
      opId = (data as { operation_id?: string }).operation_id
    }
    clearRequestId() // 已产生操作，后续新提交用新键
    await loadSession(true) // 余额以服务端刷新为准
    // P17：受理成功直接进第三级批次页（结果导向，不再停留成功卡）
    if (opId) {
      await router.replace(`/results/batch/${opId}`)
      return
    }
  } catch (e) {
    error.value = (e as { message: string }).message
    // 保留输入内容（04 §7.4）；幂等键已存，重试自动复用
  } finally {
    submitting.value = false
  }
}

function copyInvalid() {
  const items = estimate.value?.invalid_items ?? []
  const text2 = items.map((it) => `${it.line_no}: ${it.raw} (${reasonText(it.reason)})`).join('\n')
  void navigator.clipboard?.writeText(text2)
}
</script>

<template>
  <section>
    <h1 class="page-title">{{ t('submit.title') }}</h1>
    <p class="page-sub">{{ t('submit.sub') }}</p>

    <!-- 受理卡（04 §5.4 第二步）：只显示服务端返回的实际结果 -->
    <div v-if="accepted" class="card accepted">
      <p class="ok-box" role="status">{{ t('quick.accepted_msg') }}</p>
      <h3>{{ t('quick.accepted_title') }}</h3>
      <ul class="kv">
        <li>
          <span>{{ acceptedKind === 'import' ? t('quick.import_id') : t('quick.op_id') }}</span>
          <span class="mono">{{ acceptedKind === 'import' ? (accepted as ImportAccepted).import_job_id : (accepted as SubmissionAccepted).operation_id }}</span>
        </li>
        <li><span>{{ t('quick.total_count') }}</span><span class="mono">{{ accepted.total_count }}</span></li>
        <li><span>{{ t('quick.billable') }}</span><span class="mono">{{ accepted.valid_count }}</span></li>
        <li><span>{{ t('quick.free') }}</span><span class="mono">{{ accepted.free_count }}</span></li>
        <li><span>{{ t('quick.invalid') }}</span><span class="mono">{{ accepted.invalid_count }}</span></li>
        <li><span>{{ t('quick.charged') }}</span><span class="mono">{{ accepted.points_charged }}{{ t('common.points_suffix') }}</span></li>
      </ul>
      <p class="hint">{{ t('submit.auto_group_hint') }}</p>
      <div class="actions">
        <RouterLink class="btn" :to="acceptedKind === 'import' ? '/imports' : `/results/batch/${(accepted as SubmissionAccepted).operation_id}`">{{ t('common.view_progress') }}</RouterLink>
        <RouterLink v-if="acceptedKind === 'import'" class="btn ghost" to="/imports">{{ t('nav.imports') }}</RouterLink>
        <button class="btn ghost" @click="accepted = null; text = ''; fileName = null; estimate = null">{{ t('quick.continue') }}</button>
        <RouterLink class="btn ghost" to="/dashboard">{{ t('common.back_dashboard') }}</RouterLink>
      </div>
    </div>

    <template v-else>
      <div class="card">
        <label for="submit-input" class="field-label">{{ t('submit.input_label') }}</label>
        <textarea
          id="submit-input"
          v-model="text"
          class="big mono"
          :placeholder="t('submit.placeholder')"
          :disabled="fileName !== null"
        ></textarea>
        <div class="file-row">
          <label class="file-btn">
            <input ref="fileInput" type="file" accept=".txt,.csv,text/plain" @change="onFileChange" />
            {{ t('submit.upload') }}
          </label>
          <span v-if="fileName" class="hint file-chip">
            {{ fileName }}
            <button class="linklike" @click="removeFile">{{ t('submit.remove') }}</button>
          </span>
          <span v-else class="hint">{{ t('submit.paste_hint') }}</span>
        </div>

        <p class="hint" role="status">
          {{ t('common.received', { n: draft.totalLines }) }}
          <template v-if="draft.overLong.length">{{ t('common.overlong', { lines: draft.overLong.join('、') }) }}</template>
          <template v-if="isBatch">{{ t('submit.import_hint') }}</template>
        </p>
        <p v-if="overImportLimit" class="error-box" role="alert">
          {{ t('submit.over_limit', { max: MAX_IMPORT_LINES.toLocaleString() }) }}
        </p>

        <!-- 目标组选择 -->
        <div v-if="groups.length" class="group-row">
          <label for="target-group" class="field-label">{{ t('submit.target_group') }}</label>
          <select id="target-group" v-model="targetGroupId">
            <option v-for="g in groups" :key="g.id" :value="g.id">
              {{ g.name }}{{ g.is_default ? t('submit.default_group_tag') : '' }} · {{ g.tracking_count }}{{ t('submit.group_unit') }}
            </option>
          </select>
        </div>

        <!-- 实时解析面板（服务端预估接口；输入辅助，非预览步骤） -->
        <div v-if="estimate || estimating || estimateError" class="estimate-panel" aria-live="polite">
          <template v-if="estimating">{{ t('submit.parsing') }}</template>
          <template v-else-if="estimateError">
            <p class="hint">{{ estimateError }}{{ t('submit.est_error_suffix') }}</p>
          </template>
          <template v-else-if="estimate">
            <div class="estimate-stats">
              <span>{{ t('submit.est_total') }} <strong class="mono">{{ estimate.total_count }}</strong></span>
              <span>{{ t('submit.est_billable') }} <strong class="mono">{{ estimate.billable_count }}</strong></span>
              <span>{{ t('submit.est_free') }} <strong class="mono">{{ estimate.free_count }}</strong></span>
              <span>{{ t('submit.est_invalid') }} <strong class="mono">{{ estimate.invalid_items.length > 0 ? estimate.invalid_items.length + '+' : estimate.invalid_items.length }}</strong></span>
            </div>
            <details v-if="estimate.invalid_items.length">
              <summary class="hint">{{ t('submit.invalid_detail', { n: estimate.invalid_items.length }) }}</summary>
              <ul class="invalid-list">
                <li v-for="it in estimate.invalid_items" :key="it.line_no">
                  {{ t('submit.invalid_line', { line: it.line_no, raw: it.raw, reason: reasonText(it.reason) }) }}
                </li>
              </ul>
              <button class="btn ghost sm" @click="copyInvalid">{{ t('submit.copy_invalid') }}</button>
            </details>
          </template>
        </div>

        <p v-if="error" class="error-box" role="alert">{{ error }}</p>

        <!-- 成本预估条（固定在主按钮旁；常驻标注「预估，以提交结果为准」） -->
        <div class="cost-bar">
          <div class="cost-text" role="status">
            <template v-if="estimate">
              {{ t('submit.cost_will_add', { n: estimate.billable_count }) }}
              {{ t('submit.cost_estimate', { n: estimate.points_estimate }) }}
              {{ t('submit.cost_free', { n: estimate.free_count }) }}
              <span class="hint">{{ t('submit.cost_balance', { n: estimate.balance }) }}</span>
              <span v-if="estimate.insufficient" class="insufficient">
                {{ t('submit.insufficient', { n: insufficientGap }) }}
              </span>
            </template>
            <template v-else>{{ t('submit.cost_idle') }}</template>
          </div>
          <div class="actions">
            <button class="btn" :disabled="!canSubmit" @click="onSubmitClick">
              {{ submitting ? t('common.submitting') : t('common.start') }}
            </button>
            <button
              v-if="draft.totalLines > 0"
              class="btn ghost"
              @click="text = ''; fileName = null; estimate = null"
            >{{ t('common.clear') }}</button>
          </div>
          <p class="hint">{{ t('submit.fee_note') }}</p>
        </div>
      </div>

      <!-- 防呆确认卡（04 §5.4）：大批量或非默认组；确认后仍走正常提交，不入账 -->
      <div v-if="pendingSubmit" class="modal-mask" @click.self="pendingSubmit = false">
        <div class="modal card" role="dialog" aria-modal="true" :aria-label="t('submit.confirm_title')">
          <h3>{{ t('submit.confirm_title') }}</h3>
          <ul class="kv">
            <li><span>{{ t('submit.confirm_group') }}</span><strong>{{ selectedGroup?.name ?? t('submit.confirm_default') }}</strong></li>
            <li><span>{{ t('submit.confirm_count') }}</span><strong class="mono">{{ draft.totalLines }}</strong></li>
            <li><span>{{ t('submit.confirm_points') }}</span><strong class="mono">{{ estimate?.points_estimate ?? '—' }}</strong></li>
          </ul>
          <p class="hint">{{ t('submit.confirm_hint', { kind: isNonDefault ? t('submit.kind_nongroup') : t('submit.kind_batch') }) }}</p>
          <div class="actions">
            <button class="btn" @click="doSubmit">{{ t('submit.confirm_submit') }}</button>
            <button class="btn ghost" @click="pendingSubmit = false">{{ t('submit.confirm_cancel') }}</button>
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
