import { describe, it, expect, beforeEach } from 'vitest'
import {
  splitDraft,
  requestIdFor,
  clearRequestId,
  contentFingerprint,
  MAX_LINES,
  MAX_LINE_CHARS,
  DRAFT_KEY,
} from '../draft'

class MemStorage implements Storage {
  private map = new Map<string, string>()
  get length() {
    return this.map.size
  }
  clear(): void {
    this.map.clear()
  }
  getItem(k: string): string | null {
    return this.map.get(k) ?? null
  }
  key(i: number): string | null {
    return [...this.map.keys()][i] ?? null
  }
  removeItem(k: string): void {
    this.map.delete(k)
  }
  setItem(k: string, v: string): void {
    this.map.set(k, v)
  }
}

describe('splitDraft：客户端保护（04 §5.1 只做长度/空值检查）', () => {
  it('按换行切分、去空行、去首尾空白', () => {
    const d = splitDraft('  9400110200883100000  \n\n\n9400110200883100001')
    expect(d.lines).toEqual(['9400110200883100000', '9400110200883100001'])
    expect(d.totalLines).toBe(2)
    expect(d.overLimit).toBe(false)
  })

  it('超 35 行标记 overLimit，不静默截断', () => {
    const text = Array.from({ length: MAX_LINES + 1 }, (_, i) => `N${i}`).join('\n')
    const d = splitDraft(text)
    expect(d.totalLines).toBe(MAX_LINES + 1)
    expect(d.overLimit).toBe(true)
    expect(d.lines.length).toBe(MAX_LINES + 1) // 内容保留，由服务端裁决
  })

  it('超长行记录行号但不删除内容', () => {
    const long = 'X'.repeat(MAX_LINE_CHARS + 1)
    const d = splitDraft(`ok\n${long}`)
    expect(d.overLong).toEqual([2])
    expect(d.lines[1]).toBe(long)
  })

  it('纯空输入 → 空行集', () => {
    expect(splitDraft('\n\n  \n').totalLines).toBe(0)
  })
})

describe('幂等键：同内容复用、内容变更换新、成功后清除（04 §10.2）', () => {
  let store: MemStorage
  beforeEach(() => {
    store = new MemStorage()
  })

  it('同内容重试复用同一 client_request_id', () => {
    const lines = ['9400110200883100000', '9400110200883100001']
    const a = requestIdFor(lines, store)
    const b = requestIdFor(lines, store)
    expect(a).toBe(b)
  })

  it('内容不同 → 新键（避免同键不同内容冲突）', () => {
    const a = requestIdFor(['9400110200883100000'], store)
    const b = requestIdFor(['9400110200883100009'], store)
    expect(a).not.toBe(b)
  })

  it('键格式符合契约 8–50 字符', () => {
    const id = requestIdFor(['x'], store)
    expect(id.length).toBeGreaterThanOrEqual(8)
    expect(id.length).toBeLessThanOrEqual(50)
  })

  it('成功后 clearRequestId，再取为新键', () => {
    const lines = ['abc']
    const a = requestIdFor(lines, store)
    clearRequestId(store)
    expect(store.getItem(DRAFT_KEY)).toBeNull()
    const b = requestIdFor(lines, store)
    expect(b).not.toBe(a)
  })

  it('存储损坏 → 降级为新键不抛异常', () => {
    store.setItem(DRAFT_KEY, '{broken json')
    expect(() => requestIdFor(['abc'], store)).not.toThrow()
  })

  it('contentFingerprint 区分顺序不同的内容', () => {
    expect(contentFingerprint(['a', 'b'])).not.toBe(contentFingerprint(['b', 'a']))
  })
})
