/**
 * 提交草稿与幂等键（04 §5.4/§10.2）。
 *
 * 客户端保护只做长度与空值检查，不判定 USPS 格式、不静默截断（04 §5.1）。
 * 幂等键：同一草稿内容重试复用同一 client_request_id；内容变更则换新键
 * （同键不同内容会触发 idempotency_conflict）。
 */

export const MAX_LINES = 35 // 即时结果路径上限（契约 SubmissionCreate.lines）
export const MAX_LINE_CHARS = 100 // 每行 ≤100 字符（契约）
export const DRAFT_KEY = 'pt_quick_draft'

export interface DraftCheck {
  lines: string[]
  totalLines: number
  overLimit: boolean
  overLong: number[] // 超长行的行号（1 起），不截断，仅提示
}

/** 把粘贴文本切成行：保留内容原样，只按换行切分，过滤纯空行不计数超长。 */
export function splitDraft(text: string): DraftCheck {
  const raw = text.split(/\r?\n/)
  const lines: string[] = []
  const overLong: number[] = []
  for (let i = 0; i < raw.length; i++) {
    const line = raw[i].trim()
    if (line === '') continue
    lines.push(line)
    if (line.length > MAX_LINE_CHARS) overLong.push(lines.length)
  }
  return {
    lines,
    totalLines: lines.length,
    overLimit: lines.length > MAX_LINES,
    overLong,
  }
}

/** 简单内容指纹（草稿键配对用，不用于安全）。 */
export function contentFingerprint(lines: string[]): string {
  let h = 5381
  for (const line of lines) {
    for (let i = 0; i < line.length; i++) {
      h = (h * 33) ^ line.charCodeAt(i)
      h >>>= 0
    }
  }
  return `${lines.length}-${h.toString(16)}`
}

/** 生成新的幂等键（UUID v4，契约要求 8–50 字符）。 */
export function newRequestId(): string {
  return crypto.randomUUID()
}

interface StoredDraft {
  fingerprint: string
  requestId: string
}

/** 取草稿对应幂等键：内容相同复用；内容不同生成新键（幂等安全重试）。 */
export function requestIdFor(lines: string[], store: Storage = localStorage): string {
  const fp = contentFingerprint(lines)
  const raw = store.getItem(DRAFT_KEY)
  if (raw) {
    try {
      const saved = JSON.parse(raw) as StoredDraft
      if (saved.fingerprint === fp && saved.requestId) return saved.requestId
    } catch {
      /* 损坏数据按新键处理 */
    }
  }
  const id = newRequestId()
  store.setItem(DRAFT_KEY, JSON.stringify({ fingerprint: fp, requestId: id } satisfies StoredDraft))
  return id
}

/** 提交成功（已产生操作）后清除草稿键，避免后续新提交误复用。 */
export function clearRequestId(store: Storage = localStorage): void {
  store.removeItem(DRAFT_KEY)
}
