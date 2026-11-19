<script setup lang="ts">
// 积分套餐（04 §2.1 公共区）：展示规则说明；价格档位以运营配置为准，前端不自算。
</script>

<template>
  <section class="about">
    <h1 class="page-title">积分套餐</h1>
    <p class="page-sub">积分长期有效；1 个新单号扣 1 积分，30 天内重复免扣。</p>

    <div class="cards-row">
      <div class="card plan">
        <h3>试用额度</h3>
        <p class="price">赠送</p>
        <ul>
          <li>人工开通或活动发放</li>
          <li>含全部查询功能</li>
        </ul>
      </div>
      <div class="card plan">
        <h3>标准套餐</h3>
        <p class="price">按量</p>
        <ul>
          <li>1 积分 = 1 个新单号</li>
          <li>兑换码即时到账</li>
        </ul>
      </div>
      <div class="card plan">
        <h3>批量套餐</h3>
        <p class="price">联系支持</p>
        <ul>
          <li>大批量单价优惠</li>
          <li>赠送积分说明见套餐详情</li>
        </ul>
      </div>
    </div>

    <div class="card">
      <h3>计费规则</h3>
      <ul>
        <li>1 个新单号扣 1 积分；30 天内同账号同单号免扣。</li>
        <li>重复项与格式错误项不扣费；提交失败且未产生操作时不扣费。</li>
        <li>积分长期有效；实际扣费在每次提交结果中返回。</li>
      </ul>
      <p class="hint">套餐购买与充值渠道当前以人工开通为主，可登录后在积分中心使用兑换码。</p>
    </div>
    <RouterLink class="btn" to="/login">登录后查看积分中心</RouterLink>
  </section>
</template>

<style scoped>
.about { max-width: 860px; margin: 0 auto; }
.cards-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.plan .price { font-size: 22px; font-weight: 700; color: var(--brand); margin: 6px 0; }
@media (max-width: 860px) { .cards-row { grid-template-columns: 1fr; } }
</style>
