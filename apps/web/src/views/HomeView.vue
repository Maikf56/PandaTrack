<template>
  <section class="landing">
    <div class="hero">
      <h1>高效的包裹追踪<br /><span class="sub-line">尽在 PandaTracking</span></h1>
      <p class="lede">
        批量查询 USPS 物流单号，实时追踪包裹状态，轻松管理您的所有发货记录。
      </p>
      <div class="cta">
        <RouterLink class="btn lg" to="/submit">开始使用 →</RouterLink>
        <RouterLink class="btn lg ghost" to="/trial">免费试用</RouterLink>
      </div>
      <p class="hint micro">已登录？顶部导航直达工作台。</p>
    </div>

    <div class="features">
      <div v-for="f in FEATURES" :key="f.title" class="feat">
        <div class="feat-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <template v-if="f.title === '批量查询'">
              <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
            </template>
            <template v-else-if="f.title === '实时追踪'">
              <path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11Z" /><circle cx="12" cy="10" r="2.5" />
            </template>
            <template v-else>
              <path d="M3 12h4l2-7 4 14 2-7h6" />
            </template>
          </svg>
        </div>
        <h3>{{ f.title }}</h3>
        <p>{{ f.desc }}</p>
      </div>
    </div>

    <footer class="foot">
      <nav>
        <RouterLink to="/products">产品介绍</RouterLink>
        <RouterLink to="/pricing">价格</RouterLink>
        <RouterLink to="/guide">使用指南</RouterLink>
      </nav>
      <p class="hint">只展示已取得的真实 USPS 结果；查询结果在后台逐步更新。</p>
    </footer>
  </section>
</template>

<script setup lang="ts">
// 未登录首页 = 纯产品介绍页（P15，对齐竞品）：不放查询功能；
// 「开始使用」进入提交路径（未登录由路由守卫带到登录页并回跳）。
const FEATURES = [
  {
    title: '批量查询',
    desc: '一次输入多个单号，快速获取所有物流状态；大批量自动进入导入任务。',
  },
  {
    title: '实时追踪',
    desc: '查询结果实时更新，按组与批次组织，随时掌握每个包裹的动向。',
  },
  {
    title: '历史管理',
    desc: '完整的查询历史记录，方便回溯与导出；30 天内重复提交免扣积分。',
  },
]
</script>

<style scoped>
.landing { max-width: 900px; margin: 0 auto; text-align: center; }
.hero { padding: 48px 0 24px; }
.hero h1 {
  font-size: clamp(34px, 6vw, 52px); line-height: 1.15; margin: 0 0 16px;
  letter-spacing: -1px; text-wrap: pretty;
}
.sub-line { color: var(--fg-soft); }
.lede { color: var(--fg-soft); font-size: 17px; max-width: 34em; margin: 0 auto 24px; text-wrap: pretty; }
.cta { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
.btn.lg { padding: 12px 26px; font-size: 16px; min-height: 48px; }
.micro { margin-top: 10px; }
.features {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 24px; padding: 40px 0;
}
.feat-icon {
  width: 44px; height: 44px; border-radius: 12px; margin: 0 auto 10px;
  background: var(--brand-soft); color: var(--brand-strong);
  display: flex; align-items: center; justify-content: center;
}
.feat h3 { margin: 0 0 6px; font-size: 17px; }
.feat p { color: var(--fg-soft); font-size: 14px; margin: 0; text-wrap: pretty; }
.foot { padding: 16px 0 32px; border-top: 1px solid var(--line); margin-top: 16px; }
.foot nav { display: flex; gap: 20px; justify-content: center; margin-bottom: 8px; }
.foot nav a { color: var(--fg-soft); text-decoration: none; font-size: 14px; }
.foot nav a:hover { color: var(--brand); }
</style>
