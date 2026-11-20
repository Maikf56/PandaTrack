/**
 * 会话与状态字典（轻量 reactive，不引入 pinia）。
 * 余额来自服务端，前端不本地计算/乐观扣减（04 §4.2）。
 */
import { reactive, ref } from 'vue'
import { api, type AuthMe, type StatusDict } from '../api/client'

interface SessionState {
  me: AuthMe | null
  loaded: boolean
  statusDict: StatusDict | null
}

export const session = reactive<SessionState>({
  me: null,
  loaded: false,
  statusDict: null,
})

/* 轨迹语言（P15 全局切换）：'' = 原文/中文；只作用于轨迹描述机翻，
   界面与状态标签仍为中文（服务端静态字典）。持久化到 localStorage。 */
export const lang = ref(localStorage.getItem('pt_lang') ?? '')

export function setLang(v: string): void {
  lang.value = v
  if (v) localStorage.setItem('pt_lang', v)
  else localStorage.removeItem('pt_lang')
}

export async function loadSession(force = false): Promise<AuthMe | null> {
  if (session.loaded && !force) return session.me
  try {
    const { data } = await api.get<AuthMe>('/api/v1/auth/me')
    session.me = data
  } catch {
    session.me = null
  }
  session.loaded = true
  return session.me
}

export async function loadStatusDict(): Promise<StatusDict> {
  if (session.statusDict) return session.statusDict
  const { data } = await api.get<StatusDict>('/api/v1/status-dict')
  session.statusDict = data
  return data
}

export function statusLabel(key: string): string {
  const s = session.statusDict?.statuses.find((x) => x.key === key)
  return s?.label_zh ?? '其他状态' // 未知原文状态显示"其他状态"，不猜测归类（04 §7.1）
}

export function clearSession(): void {
  session.me = null
  session.loaded = false
}
