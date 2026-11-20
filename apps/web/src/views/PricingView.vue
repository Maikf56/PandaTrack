<script setup lang="ts">
// 积分套餐（04 §2.1 公共区，P16 对齐竞品结构）：
// 亮点 chips → 计费规则明细 → 需要更多积分。
// 系统暂未上线充值档位（充值由客服人工开通），页面不编造具体价格表。
const HIGHLIGHTS = [
  '查询失败不扣积分', '已完结单号不重复扣费', '注册即送 500 积分',
] as const

const RULES = [
  { item: '查询计费', detail: '每成功受理 1 个单号计 1 积分；提交前先预估，确认后才扣费。' },
  { item: '失败保护', detail: '查询失败或系统原因未取得结果，积分全额退回。' },
  { item: '重复提交', detail: '同一单号在有效期内重复提交不重复计费；已完结单号不再扣费。' },
  { item: '新客奖励', detail: '注册并通过审核后自动发放 500 积分，足够完成首批试查。' },
  { item: '充值方式', detail: '积分通过客服开通充值，量大可谈批量折扣。' },
] as const
</script>

<template>
  <section class="about">
    <h1 class="page-title">简单透明的积分价格</h1>
    <p class="page-sub">
      每查询一个 USPS 单号扣 1 积分。查询失败不扣费，注册即送试用积分。
    </p>

    <div class="chips">
      <span v-for="h in HIGHLIGHTS" :key="h" class="chip">{{ h }}</span>
    </div>

    <h2 class="sec-title">计费规则明细</h2>
    <div class="card rules-card">
      <table class="rules">
        <thead>
          <tr><th>项目</th><th>规则</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in RULES" :key="r.item">
            <td class="rule-item">{{ r.item }}</td>
            <td class="rule-detail">{{ r.detail }}</td>
          </tr>
        </tbody>
      </table>
      <p class="hint">最终计费以提交页的实时预估为准；规则调整会在本页与积分中心公告。</p>
    </div>

    <div class="more-pts">
      <h2>需要更多积分？</h2>
      <p class="hint">
        联系我们说明你的日均单号量，可开通充值并获得批量折扣；
        新注册用户也可以先领取 500 积分试用。
      </p>
      <div class="cta-row">
        <RouterLink class="btn" to="/register">免费注册领取积分</RouterLink>
        <RouterLink class="btn ghost" to="/trial">联系我们充值</RouterLink>
      </div>
    </div>
  </section>
</template>

<style scoped>
.about { max-width: 760px; margin: 0 auto; text-align: center; }
.chips { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin: 4px 0 10px; }
.chip {
  background: var(--brand-soft); color: var(--brand-strong);
  border: 1px solid var(--brand-line); border-radius: 999px;
  padding: 7px 16px; font-size: 14px; font-weight: 500;
}
.sec-title { font-size: 18px; margin: 34px 0 14px; }
.rules-card { text-align: left; padding: 0; overflow: hidden; }
.rules { width: 100%; border-collapse: collapse; }
.rules th, .rules td { text-align: left; padding: 12px 18px; border-bottom: 1px solid var(--line); }
.rules th { color: var(--fg-soft); font-weight: 500; font-size: 13px; }
.rules tbody tr:last-child td { border-bottom: none; }
.rule-item { font-weight: 600; white-space: nowrap; width: 7em; }
.rule-detail { color: var(--fg-soft); text-wrap: pretty; }
.rules-card .hint { padding: 10px 18px 14px; margin: 0; border-top: 1px dashed var(--line); }
.more-pts { padding: 26px 0 8px; }
.more-pts h2 { font-size: 22px; margin: 0 0 8px; }
.more-pts .hint { max-width: 34em; margin: 0 auto 18px; text-wrap: pretty; }
.cta-row { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
</style>
