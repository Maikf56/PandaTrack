<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminSession, api, can, ROLE_LABELS } from './api/client'
import pandaLogo from './assets/panda-logo.jpeg'

const route = useRoute()
const router = useRouter()
const isLogin = computed(() => route.name === 'login')

// 导航按角色过滤（03 §2 RBAC；后端为权威校验，这里只控可见性）
const navItems = [
  { to: '/', label: '客户管理', perm: 'customers:read' },
  { to: '/billing', label: '账务操作', perm: 'billing:read' },
  { to: '/providers', label: 'Provider 与任务', perm: 'providers:read' },
  { to: '/audit', label: '审计日志', perm: 'audit:read' },
]
const visibleNav = computed(() =>
  navItems.filter((it) => can(it.perm)),
)
const roleLabel = computed(() =>
  ROLE_LABELS[adminSession.me?.role ?? ''] ?? adminSession.me?.role ?? '',
)

async function logout() {
  try {
    await api.post('/api/v1/admin/auth/logout')
  } catch {
    /* 本地清理即可 */
  }
  adminSession.me = null
  router.push({ name: 'login' })
}
</script>

<template>
  <div v-if="isLogin" class="login-shell">
    <RouterView />
  </div>

  <div v-else class="adm-shell">
    <aside class="adm-nav">
      <div class="brand">
        <img :src="pandaLogo" alt="PandaTrack 管理端" class="brand-logo" />
      </div>
      <p class="adm-badge">管理端</p>
      <nav>
        <RouterLink v-for="it in visibleNav" :key="it.to" :to="it.to">
          {{ it.label }}
        </RouterLink>
      </nav>
      <div class="adm-footer">
        <p v-if="adminSession.me" class="hint">
          {{ adminSession.me.username }}（{{ roleLabel }}）
        </p>
        <button class="btn ghost sm" @click="logout">退出登录</button>
      </div>
    </aside>
    <main class="adm-main">
      <RouterView />
    </main>
  </div>
</template>

<style>
/* 管理端复用同一套设计令牌（04 §4.4），视觉与客户前端同源（03 §3.1 独立入口） */
:root {
  --bg: #fafaf9;
  --panel: #ffffff;
  --fg: #1c1917;
  --fg-soft: #78716c;
  --line: #e7e5e4;
  --brand: #0f766e;
  --brand-strong: #115e59;
  --brand-soft: #f0fdfa;
  --ok: #15803d;
  --ok-soft: #f0fdf4;
  --warn: #b45309;
  --warn-soft: #fffbeb;
  --err: #b91c1c;
  --err-soft: #fef2f2;
  --shadow-1: 0 1px 2px rgba(28, 25, 23, 0.05), 0 4px 12px rgba(28, 25, 23, 0.06);
  --shadow-2: 0 8px 32px rgba(28, 25, 23, 0.16);
  --radius-panel: 12px;
  --radius-ctl: 8px;
  --radius-badge: 999px;
  --dur: 160ms;
  --mono: ui-monospace, 'Cascadia Mono', 'SF Mono', Consolas, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0; color: var(--fg); background: var(--bg);
  font: 15px/1.6 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
}
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
a { color: var(--brand); }
.mono { font-family: var(--mono); word-break: break-all; font-size: 0.95em; }
.hint { color: var(--fg-soft); font-size: 13px; }

.login-shell { min-height: 100dvh; display: flex; align-items: center; justify-content: center; }
.adm-shell { min-height: 100dvh; display: flex; }
.adm-nav {
  width: 216px; flex-shrink: 0; background: var(--panel);
  border-right: 1px solid var(--line); padding: 20px 14px;
  display: flex; flex-direction: column;
  position: sticky; top: 0; height: 100dvh;
}
.brand-logo { width: 140px; height: auto; display: block; }
.adm-badge {
  display: inline-block; align-self: flex-start; margin: 10px 0 0;
  border-radius: var(--radius-badge); padding: 2px 10px; font-size: 12px;
  font-weight: 600; background: var(--brand-soft); color: var(--brand-strong);
}
.adm-nav nav { display: flex; flex-direction: column; gap: 2px; margin-top: 16px; }
.adm-nav nav a {
  padding: 8px 12px; border-radius: var(--radius-ctl); text-decoration: none;
  color: var(--fg); font-weight: 500; font-size: 14px;
  transition: background var(--dur) ease-out;
}
.adm-nav nav a:hover { background: var(--bg); }
.adm-nav nav a.router-link-active { background: var(--brand-soft); color: var(--brand-strong); font-weight: 600; }
.adm-footer { margin-top: auto; display: flex; flex-direction: column; gap: 8px; }
.adm-main { flex: 1; padding: 28px 24px 48px; max-width: 1280px; width: 100%; margin: 0 auto; }

.card {
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-panel);
  padding: 20px; margin-bottom: 16px;
}
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  border: 1px solid var(--brand); background: var(--brand); color: #fff;
  border-radius: var(--radius-ctl); padding: 10px 20px; font: inherit; font-weight: 600;
  cursor: pointer; min-height: 44px;
  transition: background var(--dur) ease-out;
}
.btn:hover:not(:disabled) { background: var(--brand-strong); }
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
.btn.ghost { background: transparent; color: var(--brand); }
.btn.danger { background: var(--err); border-color: var(--err); }
.btn.sm { padding: 6px 12px; min-height: 34px; font-weight: 500; }
input, select, textarea {
  font: inherit; color: inherit; width: 100%;
  border: 1px solid var(--line); border-radius: var(--radius-ctl); padding: 10px 12px;
  background: #fff;
}
input:focus, select:focus, textarea:focus {
  outline: none; border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-soft);
}
.error-box {
  background: var(--err-soft); border: 1px solid #fecaca; color: var(--err);
  border-radius: var(--radius-ctl); padding: 10px 14px; margin: 12px 0;
}
.ok-box {
  background: var(--ok-soft); border: 1px solid #bbf7d0; color: var(--ok);
  border-radius: var(--radius-ctl); padding: 10px 14px; margin: 12px 0;
}
.badge {
  display: inline-block; border-radius: var(--radius-badge); padding: 2px 10px;
  font-size: 13px; font-weight: 600; background: var(--brand-soft); color: var(--brand-strong);
  white-space: nowrap;
}
.badge.ok { background: var(--ok-soft); color: var(--ok); }
.badge.warn { background: var(--warn-soft); color: var(--warn); }
.badge.err { background: var(--err-soft); color: var(--err); }
.page-title { font-size: 24px; margin: 0 0 4px; }
.page-sub { color: var(--fg-soft); margin: 0 0 20px; }
table.list { width: 100%; border-collapse: collapse; background: var(--panel); border-radius: var(--radius-panel); overflow: hidden; }
table.list th, table.list td { text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--line); }
table.list th { color: var(--fg-soft); font-weight: 500; font-size: 13px; }
table.list tbody tr:hover { background: var(--bg); }
.field-label { display: block; font-weight: 600; margin-bottom: 8px; }
.form-row { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }
.form-row > div { flex: 1; min-width: 140px; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(28, 25, 23, 0.4);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal { width: min(460px, 92vw); margin: 0; box-shadow: var(--shadow-2); }
.kv { list-style: none; padding: 0; margin: 12px 0; }
.kv li { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--line); }
@media (max-width: 860px) {
  .adm-shell { flex-direction: column; }
  .adm-nav { width: 100%; height: auto; position: static; flex-direction: row; align-items: center; overflow-x: auto; }
  .adm-nav nav { flex-direction: row; }
  .adm-footer { margin-top: 0; margin-left: auto; }
  table.list { display: block; overflow-x: auto; }
}
</style>
