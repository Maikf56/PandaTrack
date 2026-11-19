/**
 * 管理端 API client（03 §3.4）：只调 /api/v1/admin/* 白名单；会话 Cookie
 * path 限定 /api/v1/admin，与其他会话隔离。
 */
import { reactive } from 'vue'

export class ApiError extends Error {
  constructor(public message: string, public status: number | null) {
    super(message)
  }
}

async function request<T>(
  method: string,
  path: string,
  opts: { json?: unknown; query?: Record<string, string | number | boolean | undefined> } = {},
): Promise<T> {
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
    if (!resp.ok) {
      // 后端 ApiProblem：{type,title,detail}；映射为白话（03 §3.4 脱敏）
      const detail =
        body && typeof body === 'object' && 'detail' in body
          ? String((body as { detail: unknown }).detail ?? '')
          : ''
      const title =
        body && typeof body === 'object' && 'title' in body
          ? String((body as { title: unknown }).title ?? '')
          : ''
      throw new ApiError(detail || title || `请求失败（${status}）`, status)
    }
    return body as T
  } catch (e) {
    if (e instanceof ApiError) throw e
    throw new ApiError('网络暂时不可用，请重试', null)
  }
}

export const api = {
  get: <T>(path: string, query?: Record<string, string | number | boolean | undefined>) =>
    request<T>('GET', path, { query }),
  post: <T>(path: string, json?: unknown, query?: Record<string, string | number | boolean | undefined>) =>
    request<T>('POST', path, { json, query }),
  patch: <T>(path: string, query?: Record<string, string | number | boolean | undefined>) =>
    request<T>('PATCH', path, { query }),
}

// ---- 管理端会话状态 ----

export interface AdminMe {
  admin_id: string
  username: string
  role: string
}

export const adminSession = reactive<{ me: AdminMe | null }>({ me: null })

// ---- 数据契约（对齐 admin_* 路由响应）----

export interface CustomerRow {
  customer_id: number
  public_id: string
  email: string
  status: string
  tenant_id: number | null
  created_at: string
  balance?: number
}

export interface ProviderRow {
  provider_code: string
  enabled: boolean
  last_success_at: string | null
  success_rate?: number | null
  circuit_state?: string | null
  [key: string]: unknown
}

export interface TaskRow {
  [key: string]: unknown
}

export interface AuditRow {
  audit_id: number
  actor_id: string | number | null
  actor_role: string | null
  action: string
  target: string | null
  detail: Record<string, unknown> | null
  created_at: string
}

export interface LedgerRow {
  ledger_id: string | number
  ledger_type: string
  points_change: number
  description: string | null
  created_at: string
}
