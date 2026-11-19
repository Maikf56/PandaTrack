/**
 * 实时通道（04 §8.2，G2 吸收）：
 * - SSE 优先，Last-Event-ID 由 EventSource 自动携带；
 * - 连接状态三态（live/polling/offline）为模块级共享，顶栏指示器读取；
 * - 可见性感知轮询：标签页不可见暂停，恢复可见立即补查；
 * - 变更追踪：客户触发式呈现（§6.3）——事件只置标记，客户点击才刷新；
 *   刷新后对状态跃迁行做 1.2s 高亮淡出（§8.2）。
 */
import { ref, onUnmounted } from 'vue'

export type ConnState = 'live' | 'polling' | 'offline'

/** 模块级共享：任意订阅者更新，顶栏指示器统一读取。 */
export const connState = ref<ConnState>('offline')

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
        connState.value = 'live'
      }
      es.onmessage = () => {
        // 只标记，由客户决定是否刷新（不自动改行、不弹通知）
        hasUpdate.value = true
      }
      es.onerror = () => {
        connected.value = false
        // EventSource 自动重连；期间降级展示为轮询态，由调用方兜底
        if (connState.value === 'live') connState.value = 'polling'
      }
    } catch {
      connected.value = false
      connState.value = 'offline'
    }
  }

  function close() {
    es?.close()
    es = null
    connected.value = false
    if (connState.value !== 'offline') connState.value = 'offline'
  }

  onUnmounted(close)

  return { connected, hasUpdate, open, close }
}

/**
 * 可见性感知轮询（04 §8.2）：后台标签页不浪费请求，前台不错过更新。
 * 恢复可见时立即补查一次，再按 interval 常规轮询；轮询只读、不扣费。
 */
export function visibilityPolling(
  tick: () => Promise<void>,
  intervalMs = 15000,
): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false

  const schedule = () => {
    if (stopped) return
    timer = setTimeout(async () => {
      if (document.visibilityState === 'visible') await runOnce()
      schedule()
    }, intervalMs)
  }

  const runOnce = async () => {
    if (stopped) return
    if (connState.value === 'live') return // SSE 在线时不重复拉全量
    if (connState.value !== 'polling') connState.value = 'polling'
    try {
      await tick()
    } catch {
      /* 失败静默，下轮再试 */
    }
  }

  const onVisibility = () => {
    if (document.visibilityState === 'visible') {
      void runOnce() // 恢复可见立即补齐期间变更
    }
    // 不可见：让定时器空转跳过（不新建请求）
  }

  document.addEventListener('visibilitychange', onVisibility)
  void runOnce()
  schedule()

  return () => {
    stopped = true
    document.removeEventListener('visibilitychange', onVisibility)
    if (timer) clearTimeout(timer)
  }
}

/**
 * 状态跃迁追踪（04 §8.2 变化感知）：刷新数据后对比上次快照，
 * 返回发生跃迁的 id 集合供列表做 1.2s 描边淡出与摘要条。
 */
export function createChangeTracker() {
  const changedIds = ref<Set<string>>(new Set())
  const lastSnapshot = new Map<string, string>()

  /** snapshot: id -> 状态 key；返回本次跃迁数量。 */
  function feed(snapshot: Map<string, string>): number {
    const changed: string[] = []
    for (const [id, status] of snapshot) {
      const prev = lastSnapshot.get(id)
      if (prev !== undefined && prev !== status) changed.push(id)
    }
    lastSnapshot.clear()
    for (const [id, status] of snapshot) lastSnapshot.set(id, status)
    changedIds.value = new Set(changed)
    return changed.length
  }

  function clear() {
    changedIds.value = new Set()
  }

  return { changedIds, feed, clear }
}

// 类型引用仅为文档；运行时无用
export type { ApiError } from '../api/client'
