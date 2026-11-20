<script setup lang="ts">
// 产品说明（04 §2.1 公共区，P16 对齐竞品结构）：
// 核心能力网格 → 支持承运商 → 使用场景 → 注意事项 → 底部 CTA。
// 只陈述真实能力（USPS / 后台逐步更新 / 真实结果），不编造未上线的功能。
const CORE = [
  {
    icon: 'batch',
    title: '批量查询',
    desc: '一次粘贴或文件导入多个 USPS 单号，自动清洗格式、去重合并，35 个一批自动受理。',
  },
  {
    icon: 'group',
    title: '分组与批次管理',
    desc: '结果按查询组和提交批次组织，每组一张状态分布图，跨批次状态一目了然。',
  },
  {
    icon: 'live',
    title: '实时更新推送',
    desc: '查询结果在后台逐步取得；页面实时感知新结果，无需手动刷新。',
  },
  {
    icon: 'export',
    title: '结果导出',
    desc: '按组或按批次导出 CSV，用于对账、客服回复和发货跟踪留档。',
  },
] as const

const SCENES = [
  '电商卖家发货跟踪', '代购/转运包裹', '客服批量回复查询',
  '财务对账留档', '退换货周期跟踪',
] as const

const NOTES = [
  '正式环境只展示已取得的真实 USPS 结果，绝不模拟或预填。',
  '查询结果在后台逐步更新：新提交的单号通常几分钟内开始返回轨迹。',
  '已完结的单号不再重复扣费；失败的查询不收取积分。',
  '提交前即可看到本次预计消耗的积分，确认后才受理。',
]
</script>

<template>
  <section class="about">
    <h1 class="page-title">产品说明</h1>
    <p class="page-sub">
      面向跨境卖家的 USPS 包裹批量查单与轨迹管理工具。
    </p>

    <h2 class="sec-title">核心能力</h2>
    <div class="core-grid">
      <div v-for="c in CORE" :key="c.icon" class="card core-card">
        <div class="core-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <template v-if="c.icon === 'batch'">
              <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
            </template>
            <template v-else-if="c.icon === 'group'">
              <rect x="3" y="4" width="8" height="6" rx="1.5" /><rect x="13" y="4" width="8" height="6" rx="1.5" />
              <rect x="3" y="14" width="8" height="6" rx="1.5" /><rect x="13" y="14" width="8" height="6" rx="1.5" />
            </template>
            <template v-else-if="c.icon === 'live'">
              <path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11Z" /><circle cx="12" cy="10" r="2.5" />
            </template>
            <template v-else>
              <path d="M12 3v12m0 0 4-4m-4 4-4-4" /><path d="M4 21h16" />
            </template>
          </svg>
        </div>
        <h3>{{ c.title }}</h3>
        <p>{{ c.desc }}</p>
      </div>
    </div>

    <h2 class="sec-title">支持的承运商</h2>
    <div class="card carrier-row">
      <span class="badge carrier-badge">USPS</span>
      <p class="hint">
        目前聚焦 USPS 全类型单号（含 Priority、First-Class、Ground Advantage 等）。
        其他承运商在规划中，暂未开放。
      </p>
    </div>

    <h2 class="sec-title">常见使用场景</h2>
    <div class="scenes">
      <span v-for="s in SCENES" :key="s" class="scene-chip">{{ s }}</span>
    </div>

    <h2 class="sec-title">容易被忽视的细节</h2>
    <div class="card">
      <ul class="notes">
        <li v-for="(n, i) in NOTES" :key="i">{{ n }}</li>
      </ul>
    </div>

    <div class="bottom-cta">
      <h2>开始批量查询 USPS 包裹</h2>
      <div class="cta-row">
        <RouterLink class="btn" to="/register">免费注册</RouterLink>
        <RouterLink class="btn ghost" to="/guide">查看使用指南</RouterLink>
      </div>
    </div>
  </section>
</template>

<style scoped>
.about { max-width: 860px; margin: 0 auto; }
.sec-title { font-size: 18px; margin: 34px 0 14px; letter-spacing: -0.2px; }
.core-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px;
}
.core-icon {
  width: 40px; height: 40px; border-radius: 10px; margin-bottom: 10px;
  background: var(--brand-soft); color: var(--brand-strong);
  display: flex; align-items: center; justify-content: center;
}
.core-card h3 { margin: 0 0 6px; font-size: 16px; }
.core-card p { color: var(--fg-soft); font-size: 14px; margin: 0; text-wrap: pretty; }
.carrier-row { display: flex; align-items: center; gap: 14px; }
.carrier-badge { font-size: 15px; padding: 6px 16px; }
.carrier-row .hint { margin: 0; }
.scenes { display: flex; flex-wrap: wrap; gap: 10px; }
.scene-chip {
  background: var(--panel); border: 1px solid var(--line); border-radius: 999px;
  padding: 7px 16px; font-size: 14px; color: var(--fg-soft);
}
.notes { margin: 0; padding-left: 20px; display: grid; gap: 8px; color: var(--fg-soft); }
.bottom-cta { text-align: center; padding: 40px 0 16px; }
.bottom-cta h2 { font-size: 22px; margin: 0 0 18px; }
.cta-row { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
</style>
