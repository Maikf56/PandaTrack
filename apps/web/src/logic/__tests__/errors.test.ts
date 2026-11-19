import { describe, it, expect } from 'vitest'
import { mapError, NETWORK_ERROR } from '../errors'

describe('mapError：已知错误码', () => {
  it('insufficient_points → 去积分中心 + extra 透传', () => {
    const e = mapError(402, {
      detail: { code: 'insufficient_points', message: 'x', extra: { required: 5, available: 1 } },
    })
    expect(e.code).toBe('insufficient_points')
    expect(e.message).toBe('积分余额不足')
    expect(e.action).toBe('go_wallet')
    expect(e.extra).toEqual({ required: 5, available: 1 })
  })

  it('idempotency_conflict 保持冲突语义', () => {
    const e = mapError(409, { detail: { code: 'idempotency_conflict', message: '' } })
    expect(e.action).toBeNull()
    expect(e.message).toContain('重新发起')
  })

  it('provider_unavailable → 服务暂停白话 + wait', () => {
    const e = mapError(503, { detail: { code: 'provider_unavailable', message: '' } })
    expect(e.message).toContain('已提交任务会保留')
    expect(e.action).toBe('wait')
  })
})

describe('mapError：未知码按 HTTP 状态兜底', () => {
  it('未知码 + 429 → rate_limited 白话', () => {
    const e = mapError(429, { detail: { code: 'weird_new_code', message: 'internal jargon' } })
    expect(e.code).toBe('rate_limited')
    expect(e.message).toBe('操作过于频繁，请稍后再试')
  })

  it('未知码 + 5xx → internal_error 白话，不回显内部信息', () => {
    const e = mapError(500, { detail: { code: 'db_conn_refused', message: 'psycopg: ...' } })
    expect(e.message).toBe('系统繁忙，请稍后再试')
    expect(e.message).not.toContain('psycopg')
  })

  it('无 detail 结构 → 按 invalid_input 兜底', () => {
    const e = mapError(400, 'not json')
    expect(e.code).toBe('invalid_input')
  })

  it('网络失败（无响应）→ retry', () => {
    expect(mapError(null, null)).toEqual(NETWORK_ERROR)
    expect(NETWORK_ERROR.action).toBe('retry')
  })
})
