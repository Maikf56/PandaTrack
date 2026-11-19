/**
 * SSE 订阅（04 §8.2）：客户打开进度页才订阅；Last-Event-ID 由 EventSource 自动携带。
 * 客户触发式呈现（04 §6.3）：事件到达只置 hasUpdate 标记，不自动改当前页面行状态。
 */
import { ref, onUnmounted } from 'vue'
import type { ApiError } from '../api/client'

export function useSse(path = '/api/v1/events') {
  const connected = ref(false)
  const hasUpdate = ref(false)
  let es: EventSource | null = null

  function open() {
    if (es) return
    try {
      es = new EventSource(path, { withCredentials: true })
      es.onopen = () => {
        connected.value = true
      }
      es.onmessage = () => {
        // 只标记，由客户决定是否刷新（不自动改行、不弹通知）
        hasUpdate.value = true
      }
      es.onerror = () => {
        // 断线：EventSource 自动重连；若连续失败由调用方退避轮询兜底
        connected.value = false
      }
    } catch {
      connected.value = false
    }
  }

  function close() {
    es?.close()
    es = null
    connected.value = false
  }

  onUnmounted(close)

  return { connected, hasUpdate, open, close }
}

/** SSE 不可用时的退避只读轮询（04 §8.2：轮询不新建任务/不扣费）。 */
export function backoffPolling(
  tick: () => Promise<void>,
  initialDelayMs = 15000,
  maxDelayMs = 30000,
): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  let delay = initialDelayMs
  let stopped = false
  const run = async () => {
    if (stopped) return
    try {
      await tick()
    } catch {
      /* 失败静默，下轮再试 */
    }
    timer = setTimeout(run, delay)
    delay = Math.min(Math.round(delay * 1.2), maxDelayMs)
  }
  void run()
  return () => {
    stopped = true
    if (timer) clearTimeout(timer)
  }
}

// 类型引用仅为文档；运行时无用
export type { ApiError }
