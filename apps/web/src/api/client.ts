/**
 * API client（04 §9.3：客户端只调 /api/v1/* 白名单；不发送第三方）。
 * 错误统一走 logic/errors 映射为白话文案。
 */
import { mapError, type ClientError } from '../logic/errors'

export class ApiError extends Error {
  constructor(public err: ClientError, public status: number | null) {
    super(err.message)
  }
}

async function request<T>(
  method: string,
  path: string,
  opts: { json?: unknown; query?: Record<string, string | number | undefined> } = {},
): Promise<{ data: T; status: number }> {
  const url = new URL(path, window.location.origin)
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined) url.searchParams.set(k, String(v))
  }
  let status: number | null = null
  try {
    const resp = await fetch(url.toString(), {
      method,
      credentials: 'same-origin',
      headers: opts.json !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.json !== undefined ? JSON.stringify(opts.json) : undefined,
    })
    status = resp.status
    const text = await resp.text()
    const body: unknown = text ? JSON.parse(text) : null
    if (!resp.ok) throw new ApiError(mapError(status, body), status)
    return { data: body as T, status }
  } catch (e) {
    if (e instanceof ApiError) throw e
    throw new ApiError(mapError(null, null), null)
  }
}

export const api = {
  get: <T>(path: string, query?: Record<string, string | number | undefined>) =>
    request<T>('GET', path, { query }),
  post: <T>(path: string, json?: unknown) => request<T>('POST', path, { json }),
  patch: <T>(path: string, json?: unknown) => request<T>('PATCH', path, { json }),
  del: <T>(path: string) => request<T>('DELETE', path),
}

// ---- 契约类型（对齐 packages/contracts，前端只依赖 09 定义字段）----

export interface AuthMe {
  customer_id: string
  email: string
  role: string
  tenant_id: string | null
  balance: number
}

export interface SubmissionAccepted {
  operation_id: string
  total_count: number
  valid_count: number
  invalid_count: number
  points_charged: number
  free_count: number
  invalid_items: { line_no: number; raw: string; reason: string }[]
}

export interface OperationSummary {
  id: string
  state: string
  total_count: number
  valid_count: number
  invalid_count: number
  points_charged: number
  created_at: string
}

export interface OperationProgress {
  id: string
  state: string
  total_count: number
  valid_count: number
  invalid_count: number
  points_charged: number
  current_batch?: number
  total_batches?: number
}

export interface TrackingEvent {
  status_key: string
  label_zh: string
  description: string | null
  time_confidence: string | null
  occurred_at?: string | null
  location?: string | null
  event_code?: string | null
}

export interface TrackingView {
  id: string
  normalized_number: string
  status_key: string
  label_zh: string
  is_terminal: boolean
  simulated: boolean
  events: TrackingEvent[]
  next_sync_at?: string | null
  last_success_at?: string | null
}

export interface CheckUpdateResult {
  customer_tracking_id: string
  fresh: boolean
  will_fetch: boolean
}

export interface BillingSummary {
  balance: number
  frozen: number
  lifetime_consumed: number
}

export interface LedgerEntry {
  ledger_id: string
  ledger_type: string
  points_change: number
  description: string | null
  created_at: string
}

export interface StatusDict {
  statuses: { key: string; label_zh: string; terminal: boolean }[]
  item_state_enum: string[]
}

// ---- 次要页面契约（04 §5.8-5.12，对齐 contracts/groups_exports）----

export interface GroupView {
  id: string
  name: string
  is_default: boolean
  archived: boolean
  tracking_count: number
  batch_count: number
  status_distribution: Record<string, number>
  created_at: string
}

export interface BatchView {
  id: string
  state: string
  total_count: number
  valid_count: number
  points_charged: number
  group_name: string | null
  created_at: string
  updated_at: string
}

export interface BatchDetail {
  id: string
  state: string
  total_count: number
  valid_count: number
  invalid_count: number
  points_charged: number
  completed: number
  processing: number
  missing: number
  created_at: string
  updated_at: string
}

export interface ImportJobView {
  id: string
  file_name: string | null
  status: string
  total: number
  done: number
  enqueued: number
  success_count: number
  failed_count: number
  skipped_count: number
  duplicate_count: number
  operation_id: string | null
  created_at: string
}

export interface ExportJobView {
  id: string
  scope: string
  scope_ref: string | null
  format: string
  file_name: string | null
  row_count: number
  status: string
  expired: boolean
  expires_at: string | null
  created_at: string
  download_url?: string | null
}

export interface StatsView {
  days: number
  submissions: number
  tracking_count: number
  points_charged: number
  waived_count: number
  status_distribution: Record<string, number>
  daily: { date: string; submissions: number }[]
}

export interface SessionView {
  id: number
  created_at: string
  expires_at: string
  revoked: boolean
  current: boolean
}

// ---- 预估与导入（04 §5.4/§5.9，对齐 contracts/submission）----

export interface SubmissionEstimate {
  total_count: number
  billable_count: number
  free_count: number
  points_estimate: number
  balance: number
  insufficient: boolean
  result_counts: Record<string, number>
  invalid_items: { line_no: number; raw: string; reason: string }[]
  estimated: boolean
}

export interface ImportAccepted {
  import_job_id: string
  operation_id: string
  total_count: number
  valid_count: number
  invalid_count: number
  points_charged: number
  free_count: number
}
