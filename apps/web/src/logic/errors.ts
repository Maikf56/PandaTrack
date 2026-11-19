/**
 * 错误映射（04 §7.4）：服务端错误码 → 白话文案 + 可执行动作。
 * 权威源：pandatrack_common/codes.py（09 §4）。前端不得显示内部信息。
 */

export type ErrorAction =
  | 'retry' // 网络重试（复用幂等键）
  | 'relogin' // 重新登录（保留草稿）
  | 'go_wallet' // 去积分中心（保留输入）
  | 'open_operation' // 打开已有操作记录（幂等重放）
  | 'shrink_input' // 删减后重试或拆分提交
  | 'wait' // 稍后再试 / 联系支持
  | 'back_workspace' // 返回工作台
  | null

export interface ClientError {
  code: string
  message: string
  action: ErrorAction
  /** 服务端附带的扩展字段（如 insufficient_points 的 required/available）。 */
  extra?: Record<string, unknown>
}

const CODE_MAP: Record<string, { message: string; action: ErrorAction }> = {
  unauthorized: { message: '邮箱或密码不正确', action: null },
  session_expired: { message: '登录已过期，请重新登录', action: 'relogin' },
  forbidden: { message: '没有权限执行此操作', action: 'back_workspace' },
  invalid_input: { message: '提交的内容有误，请检查后重试', action: null },
  request_too_large: {
    message: '单次提交数量超出上限，请删减后重试或拆分为多次提交',
    action: 'shrink_input',
  },
  not_found: { message: '没有找到对应记录', action: 'back_workspace' },
  idempotency_conflict: {
    message: '该请求编号已用于另一份提交内容，请重新发起',
    action: null,
  },
  insufficient_points: { message: '积分余额不足', action: 'go_wallet' },
  redemption_code_invalid: { message: '兑换码无效或已核销', action: null },
  provider_disabled: { message: '查询服务暂未开放', action: 'wait' },
  provider_unavailable: {
    message: '查询服务暂时不可用，已提交任务会保留，请稍后查看',
    action: 'wait',
  },
  processing_failed: { message: '任务处理失败，请联系支持', action: 'wait' },
  rate_limited: { message: '操作过于频繁，请稍后再试', action: 'wait' },
  internal_error: { message: '系统繁忙，请稍后再试', action: 'wait' },
}

/** 网络层失败（无响应）。 */
export const NETWORK_ERROR: ClientError = {
  code: 'network',
  message: '网络暂时不可用，请检查连接后重试',
  action: 'retry',
}

/** 把服务端错误体 {detail:{code,message,...}} 或 HTTP 状态映射为客户端错误。 */
export function mapError(
  status: number | null,
  body: unknown,
): ClientError {
  if (status === null) return NETWORK_ERROR
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? (body as { detail: unknown }).detail
      : null
  const code =
    detail && typeof detail === 'object' && 'code' in detail
      ? String((detail as { code: unknown }).code)
      : ''
  const extra =
    detail && typeof detail === 'object' && 'extra' in detail
      ? ((detail as { extra: Record<string, unknown> }).extra ?? undefined)
      : undefined
  const known = CODE_MAP[code]
  if (known) return { code, message: known.message, action: known.action, extra }
  // 未知码按 HTTP 状态兜底，不显示内部信息（09 §3）。
  const fallbackByStatus: Record<number, string> = {
    401: 'unauthorized',
    402: 'insufficient_points',
    403: 'forbidden',
    413: 'request_too_large',
    429: 'rate_limited',
  }
  const fallbackCode =
    fallbackByStatus[status] ?? (status >= 500 ? 'internal_error' : 'invalid_input')
  const fb = CODE_MAP[fallbackCode]
  return { code: fallbackCode, message: fb.message, action: fb.action, extra }
}
