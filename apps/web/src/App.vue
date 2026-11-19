<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { loadSession, session, clearSession } from './composables/session'

const route = useRoute()
const router = useRouter()

const isWorkspace = computed(() => route.meta.auth === true)
const isLoggedIn = computed(() => session.me !== null)

loadSession()

async function logout() {
  try {
    await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'same-origin' })
  } catch {
    /* 网络失败也本地清理会话状态（04 §5.2） */
  }
  clearSession()
  router.push({ name: 'login' })
}
</script>

<template>
  <!-- 公共区轻量导航；工作台用 左侧导航+顶部账户栏（04 §4.1/§4.2） -->
  <div v-if="!isWorkspace" class="pub-shell">
    <header class="pub-nav">
      <RouterLink to="/" class="brand">PandaTrack</RouterLink>
      <nav>
        <RouterLink to="/guide">使用指南</RouterLink>
        <template v-if="!isLoggedIn">
          <RouterLink to="/login">登录</RouterLink>
        </template>
        <template v-else>
          <RouterLink to="/dashboard">工作台</RouterLink>
          <button class="linklike" @click="logout">退出</button>
        </template>
      </nav>
    </header>
    <main class="pub-main">
      <RouterView />
    </main>
    <footer class="pub-footer">
      正式环境只展示已取得的真实 USPS 结果；查询结果在后台逐步更新。
    </footer>
  </div>

  <div v-else class="ws-shell">
    <aside class="ws-nav">
      <RouterLink to="/" class="brand">PandaTrack</RouterLink>
      <nav>
        <div class="nav-group">查询</div>
        <RouterLink to="/quick">临时快查</RouterLink>
        <RouterLink to="/results">结果列表</RouterLink>
        <div class="nav-group">账户</div>
        <RouterLink to="/wallet">积分中心</RouterLink>
        <div class="nav-group">帮助</div>
        <RouterLink to="/guide">使用指南</RouterLink>
      </nav>
    </aside>
    <div class="ws-body">
      <header class="ws-topbar">
        <span v-if="session.me" class="topbar-mail">{{ session.me.email }}</span>
        <span v-if="session.me" class="topbar-balance" role="status">
          积分余额：{{ session.me.balance }}
        </span>
        <button class="btn ghost sm" @click="logout">退出登录</button>
      </header>
      <main class="ws-main">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style>
:root {
  --fg: #1a2233;
  --fg-soft: #5b6478;
  --bg: #f5f7fa;
  --card: #ffffff;
  --line: #dde3ec;
  --brand: #2456d6;
  --brand-soft: #e8eefc;
  --ok: #177245;
  --warn: #b06000;
  --err: #b3261e;
  --mono: ui-monospace, 'Cascadia Mono', Consolas, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--fg);
  background: var(--bg);
  font: 15px/1.6 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
}
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
.brand { font-weight: 700; color: var(--brand); text-decoration: none; font-size: 18px; }
.linklike { background: none; border: none; color: var(--fg-soft); cursor: pointer; font: inherit; padding: 0; }
a { color: var(--brand); }

/* 公共区 */
.pub-shell { min-height: 100dvh; display: flex; flex-direction: column; }
.pub-nav {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 24px; background: var(--card); border-bottom: 1px solid var(--line);
}
.pub-nav nav { display: flex; gap: 18px; align-items: center; }
.pub-main { flex: 1; width: 100%; max-width: 1280px; margin: 0 auto; padding: 32px 24px; }
.pub-footer { padding: 16px 24px; color: var(--fg-soft); font-size: 13px; text-align: center; }

/* 工作台 */
.ws-shell { min-height: 100dvh; display: flex; }
.ws-nav {
  width: 200px; flex-shrink: 0; background: var(--card);
  border-right: 1px solid var(--line); padding: 20px 14px;
  display: flex; flex-direction: column; gap: 6px;
}
.ws-nav nav { display: flex; flex-direction: column; gap: 4px; margin-top: 16px; }
.ws-nav nav a { padding: 8px 10px; border-radius: 8px; text-decoration: none; color: var(--fg); }
.ws-nav nav a.router-link-active { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
.nav-group { font-size: 12px; color: var(--fg-soft); padding: 10px 10px 2px; }
.ws-body { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.ws-topbar {
  display: flex; align-items: center; gap: 16px; justify-content: flex-end;
  padding: 10px 24px; background: var(--card); border-bottom: 1px solid var(--line);
}
.topbar-mail { color: var(--fg-soft); }
.topbar-balance { font-weight: 600; }
.ws-main { flex: 1; padding: 28px 24px; max-width: 1280px; width: 100%; margin: 0 auto; }

/* 通用组件样式 */
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 20px; margin-bottom: 16px;
}
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  border: 1px solid var(--brand); background: var(--brand); color: #fff;
  border-radius: 8px; padding: 10px 20px; font: inherit; font-weight: 600;
  cursor: pointer; min-height: 44px;
}
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
.btn.ghost { background: transparent; color: var(--brand); }
.btn.sm { padding: 6px 12px; min-height: 34px; font-weight: 500; }
textarea, input {
  font: inherit; color: inherit; width: 100%;
  border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
  background: #fff;
}
textarea.big { min-height: 160px; resize: vertical; }
.mono { font-family: var(--mono); word-break: break-all; }
.hint { color: var(--fg-soft); font-size: 13px; }
.error-box {
  background: #fdf1f0; border: 1px solid #f3c2bf; color: var(--err);
  border-radius: 8px; padding: 10px 14px; margin: 12px 0;
}
.ok-box {
  background: #eef7f1; border: 1px solid #bfe3cc; color: var(--ok);
  border-radius: 8px; padding: 10px 14px; margin: 12px 0;
}
.badge {
  display: inline-block; border-radius: 999px; padding: 2px 10px;
  font-size: 13px; font-weight: 600; background: var(--brand-soft); color: var(--brand);
}
.badge.terminal { background: #eef7f1; color: var(--ok); }
.badge.warn { background: #fdf3e6; color: var(--warn); }
.page-title { font-size: 22px; margin: 0 0 4px; }
.page-sub { color: var(--fg-soft); margin: 0 0 20px; }
table.list { width: 100%; border-collapse: collapse; background: var(--card); border-radius: 12px; overflow: hidden; }
table.list th, table.list td { text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--line); }
table.list th { color: var(--fg-soft); font-weight: 500; font-size: 13px; }

@media (max-width: 860px) {
  .ws-shell { flex-direction: column; }
  .ws-nav { width: 100%; flex-direction: row; align-items: center; overflow-x: auto; padding: 10px 14px; }
  .ws-nav nav { flex-direction: row; margin-top: 0; gap: 10px; }
  .nav-group { display: none; }
  table.list { display: block; overflow-x: auto; }
}
</style>
