<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { loadSession, session, clearSession } from './composables/session'
import { connState } from './composables/sse'
import pandaLogo from './assets/panda-logo.jpeg'

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

/* 连接状态指示器（04 §8.2）：live/polling/offline 三态小圆点，配文字不靠颜色。 */
const connText = computed(() => {
  if (connState.value === 'live') return '实时'
  if (connState.value === 'polling') return '轮询'
  return '离线'
})
</script>

<template>
  <!-- 公共区轻量导航；工作台用 左侧导航+顶部账户栏（04 §4.1/§4.2） -->
  <div v-if="!isWorkspace" class="pub-shell">
    <header class="pub-nav">
      <RouterLink to="/" class="brand">
        <img :src="pandaLogo" alt="PandaTrack LOGO" class="brand-logo" />
        <span class="brand-name">PandaTracking</span>
      </RouterLink>
      <nav>
        <RouterLink to="/products">产品说明</RouterLink>
        <RouterLink to="/pricing">积分套餐</RouterLink>
        <RouterLink to="/guide">使用指南</RouterLink>
        <template v-if="!isLoggedIn">
          <RouterLink to="/login">登录</RouterLink>
          <RouterLink to="/trial" class="nav-cta">申请试用</RouterLink>
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
      <RouterLink to="/dashboard" class="brand">
        <img :src="pandaLogo" alt="PandaTrack LOGO" class="brand-logo" />
        <span class="brand-name">PandaTracking</span>
      </RouterLink>
      <nav>
        <div class="nav-group">查询</div>
        <RouterLink to="/submit">提交单号</RouterLink>
        <RouterLink to="/quick">临时快查</RouterLink>
        <RouterLink to="/results">结果列表</RouterLink>
        <RouterLink to="/stats">查询统计</RouterLink>
        <div class="nav-group">记录</div>
        <RouterLink to="/submissions">提交记录</RouterLink>
        <RouterLink to="/groups">组与批次</RouterLink>
        <RouterLink to="/imports">导入任务</RouterLink>
        <RouterLink to="/exports">导出任务</RouterLink>
        <div class="nav-group">账户</div>
        <RouterLink to="/wallet">积分中心</RouterLink>
        <RouterLink to="/settings">设置</RouterLink>
        <div class="nav-group">帮助</div>
        <RouterLink to="/guide">使用指南</RouterLink>
        <RouterLink to="/products">产品说明</RouterLink>
      </nav>
    </aside>
    <div class="ws-body">
      <header class="ws-topbar">
        <span class="conn-dot" :class="connState" :title="`连接状态：${connText}`">
          <span class="dot" aria-hidden="true"></span>{{ connText }}
        </span>
        <span v-if="session.me" class="topbar-mail">{{ session.me.email }}</span>
        <span v-if="session.me" class="topbar-balance" role="status">
          余额 <strong class="mono">{{ session.me.balance }}</strong> 积分
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
/* ===== 设计系统（04 §4.4，G2 吸收）===== */
:root {
  /* 色彩：中性灰阶骨架 + 单一强调色青绿；语义色仅用于物流状态 */
  --bg: #fafaf9;
  --panel: #ffffff;
  --fg: #1c1917;
  --fg-soft: #78716c;
  --line: #e7e5e4;
  --brand: #0f766e;
  --brand-strong: #115e59;
  --brand-soft: #f0fdfa;
  --brand-line: #99f6e4;
  --ok: #15803d;
  --ok-soft: #f0fdf4;
  --warn: #b45309;
  --warn-soft: #fffbeb;
  --err: #b91c1c;
  --err-soft: #fef2f2;
  --orange: #c2410c;
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
  margin: 0;
  color: var(--fg);
  background: var(--bg);
  font: 15px/1.6 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
}
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
.brand {
  display: inline-flex; align-items: center; gap: 10px;
  text-decoration: none; color: var(--fg);
}
.brand-logo { width: 132px; height: auto; display: block; }
.brand-name { font-weight: 700; font-size: 18px; color: var(--fg); letter-spacing: -0.2px; }
.linklike { background: none; border: none; color: var(--fg-soft); cursor: pointer; font: inherit; padding: 0; }
a { color: var(--brand); }

/* ===== 公共区 ===== */
.pub-shell { min-height: 100dvh; display: flex; flex-direction: column; }
.pub-nav {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 24px; background: var(--panel); border-bottom: 1px solid var(--line);
  position: sticky; top: 0; z-index: 10;
}
.pub-nav nav { display: flex; gap: 20px; align-items: center; }
.pub-nav nav a { color: var(--fg-soft); text-decoration: none; font-weight: 500; transition: color var(--dur) ease-out; }
.pub-nav nav a:hover { color: var(--fg); }
.pub-nav nav a.router-link-active { color: var(--brand); }
.pub-nav .nav-cta {
  color: #fff !important; background: var(--brand); padding: 8px 16px;
  border-radius: var(--radius-ctl); font-weight: 600;
}
.pub-nav .nav-cta:hover { background: var(--brand-strong); }
.pub-main { flex: 1; width: 100%; max-width: 1280px; margin: 0 auto; padding: 36px 24px; }
.pub-footer { padding: 16px 24px; color: var(--fg-soft); font-size: 13px; text-align: center; }

/* ===== 工作台 ===== */
.ws-shell { min-height: 100dvh; display: flex; }
.ws-nav {
  width: 216px; flex-shrink: 0; background: var(--panel);
  border-right: 1px solid var(--line); padding: 18px 14px;
  display: flex; flex-direction: column; gap: 6px;
  position: sticky; top: 0; height: 100dvh; overflow-y: auto;
}
.ws-nav nav { display: flex; flex-direction: column; gap: 2px; margin-top: 14px; }
.ws-nav nav a {
  padding: 8px 12px; border-radius: var(--radius-ctl); text-decoration: none;
  color: var(--fg); font-weight: 500; font-size: 14px;
  transition: background var(--dur) ease-out, color var(--dur) ease-out;
}
.ws-nav nav a:hover { background: var(--bg); }
.ws-nav nav a.router-link-active { background: var(--brand-soft); color: var(--brand-strong); font-weight: 600; }
.nav-group { font-size: 12px; color: var(--fg-soft); padding: 12px 12px 4px; letter-spacing: 0.5px; }
.ws-body { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.ws-topbar {
  display: flex; align-items: center; gap: 16px; justify-content: flex-end;
  padding: 10px 24px; background: var(--panel); border-bottom: 1px solid var(--line);
  position: sticky; top: 0; z-index: 10;
}
.conn-dot {
  display: inline-flex; align-items: center; gap: 6px; margin-right: auto;
  font-size: 13px; color: var(--fg-soft);
}
.conn-dot .dot { width: 8px; height: 8px; border-radius: 999px; background: var(--fg-soft); }
.conn-dot.live .dot { background: var(--ok); box-shadow: 0 0 0 3px var(--ok-soft); }
.conn-dot.polling .dot { background: var(--warn); box-shadow: 0 0 0 3px var(--warn-soft); }
.conn-dot.offline .dot { background: var(--fg-soft); }
.topbar-mail { color: var(--fg-soft); font-size: 14px; }
.topbar-balance { font-size: 14px; }
.ws-main { flex: 1; padding: 28px 24px 48px; max-width: 1280px; width: 100%; margin: 0 auto; }

/* ===== 通用组件 ===== */
.card {
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius-panel);
  padding: 20px; margin-bottom: 16px;
}
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  border: 1px solid var(--brand); background: var(--brand); color: #fff;
  border-radius: var(--radius-ctl); padding: 10px 20px; font: inherit; font-weight: 600;
  cursor: pointer; min-height: 44px;
  transition: background var(--dur) ease-out, border-color var(--dur) ease-out;
}
.btn:hover:not(:disabled) { background: var(--brand-strong); border-color: var(--brand-strong); }
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
.btn.ghost { background: transparent; color: var(--brand); }
.btn.ghost:hover:not(:disabled) { background: var(--brand-soft); }
.btn.danger { background: var(--err); border-color: var(--err); }
.btn.sm { padding: 6px 12px; min-height: 34px; font-weight: 500; }
textarea, input, select {
  font: inherit; color: inherit; width: 100%;
  border: 1px solid var(--line); border-radius: var(--radius-ctl); padding: 10px 12px;
  background: #fff;
  transition: border-color var(--dur) ease-out, box-shadow var(--dur) ease-out;
}
textarea:focus, input:focus, select:focus {
  outline: none; border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-soft);
}
textarea.big { min-height: 160px; resize: vertical; }
.mono { font-family: var(--mono); word-break: break-all; font-size: 0.95em; }
.hint { color: var(--fg-soft); font-size: 13px; }
.error-box {
  background: var(--err-soft); border: 1px solid #fecaca; color: var(--err);
  border-radius: var(--radius-ctl); padding: 10px 14px; margin: 12px 0;
}
.ok-box {
  background: var(--ok-soft); border: 1px solid #bbf7d0; color: var(--ok);
  border-radius: var(--radius-ctl); padding: 10px 14px; margin: 12px 0;
}
.warn-box {
  background: var(--warn-soft); border: 1px solid #fde68a; color: var(--warn);
  border-radius: var(--radius-ctl); padding: 10px 14px; margin: 12px 0;
}
.badge {
  display: inline-block; border-radius: var(--radius-badge); padding: 2px 10px;
  font-size: 13px; font-weight: 600; background: var(--brand-soft); color: var(--brand-strong);
  white-space: nowrap;
}
.badge.terminal { background: var(--ok-soft); color: var(--ok); }
.badge.warn { background: var(--warn-soft); color: var(--warn); }
.badge.err { background: var(--err-soft); color: var(--err); }
.page-title { font-size: 24px; margin: 0 0 4px; letter-spacing: -0.3px; }
.page-sub { color: var(--fg-soft); margin: 0 0 20px; }
table.list { width: 100%; border-collapse: collapse; background: var(--panel); border-radius: var(--radius-panel); overflow: hidden; }
table.list th, table.list td { text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--line); }
table.list th { color: var(--fg-soft); font-weight: 500; font-size: 13px; }
table.list tbody tr { transition: background var(--dur) ease-out; }
table.list tbody tr:hover { background: var(--bg); }
/* 状态跃迁高亮：1.2s 描边淡出（04 §8.2） */
@keyframes flash-line {
  0% { background: var(--brand-soft); box-shadow: inset 2px 0 0 var(--brand); }
  100% { background: transparent; box-shadow: inset 2px 0 0 transparent; }
}
tr.flash { animation: flash-line 1.2s ease-out; }
/* 空状态即引导（04 §5.13/§7.3） */
.empty-state { text-align: center; padding: 40px 20px; color: var(--fg-soft); }
.empty-state .btn { margin-top: 12px; }
.field-label { display: block; font-weight: 600; margin-bottom: 8px; }
.kv { list-style: none; padding: 0; margin: 12px 0; }
.kv li { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--line); }

@media (max-width: 860px) {
  .ws-shell { flex-direction: column; }
  .ws-nav {
    width: 100%; height: auto; position: static; flex-direction: row;
    align-items: center; overflow-x: auto; padding: 10px 14px;
  }
  .ws-nav nav { flex-direction: row; margin-top: 0; gap: 10px; }
  .nav-group { display: none; }
  .brand-logo { width: 96px; }
  table.list { display: block; overflow-x: auto; }
}
</style>
