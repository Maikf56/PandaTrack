<script setup lang="ts">
// 产品说明（04 §2.1 公共区）：批量查询、历史结果、状态与更新方式。
</script>

<template>
  <section class="about">
    <h1 class="page-title">产品说明</h1>
    <p class="page-sub">面向批量 USPS 单号查询的真实结果工作台。</p>

    <div class="card">
      <h3>批量查询</h3>
      <p>粘贴多行单号直接开始查询；单次最多 35 条走即时结果路径，更多数量将通过导入任务分批处理（单次受理上限 1,000,000 条）。每个批次自动归入你的默认组，便于回溯。</p>
    </div>
    <div class="card">
      <h3>历史结果</h3>
      <p>所有查询结果长期保存并可筛选查看；每个结果显示取得时间、最近有效更新时间和是否沿用旧结果。</p>
    </div>
    <div class="card">
      <h3>状态与更新方式</h3>
      <p>后台按状态分层保鲜非终态单号；你打开页面或点「检查更新」时才读取最新结果。检查更新由服务端决定是否真正访问查询源——终态或 30 天内刚更新的单号会明确标注「沿用现有结果」。</p>
    </div>
    <div class="card">
      <h3>结果真实性</h3>
      <p>正式环境只展示已取得的真实结果；等待、服务暂停或暂未获取都有明确状态，不会伪装成功。</p>
    </div>
    <RouterLink class="btn" to="/login">登录开始查询</RouterLink>
  </section>
</template>

<style scoped>
.about { max-width: 720px; margin: 0 auto; }
</style>
