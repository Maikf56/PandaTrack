<script setup lang="ts">
import { computed } from 'vue'
import { t } from '../i18n'

// 使用指南（04 §5.12，P16 对齐竞品帮助中心结构）：
// 左侧目录（锚点跳转）+ 快速开始四步 + 分节说明 + 页脚上一节/下一节。
// 文案沿用既有 i18n 词典，不重复维护两份。
const SECTIONS = computed(() => [
  { id: 'quick-start', label: '快速开始' },
  { id: 'input', label: t('guide.input_title') },
  { id: 'fee', label: t('guide.fee_title') },
  { id: 'results', label: t('guide.results_title') },
  { id: 'refresh', label: t('guide.refresh_title') },
  { id: 'account', label: t('guide.account_title') },
  { id: 'anomaly', label: t('guide.anomaly_title') },
])

const STEPS = [
  { n: 1, title: '注册账号', body: '填写邮箱与密码完成注册；管理员审核通过后即可登录，并自动获得 500 试用积分。' },
  { n: 2, title: '提交查询', body: '进入「提交单号」，粘贴 USPS 单号（每行一个），确认预估积分后开始查询；也可使用「临时快查」处理临时需求。' },
  { n: 3, title: '查看结果', body: '「我的查询」按查询组与提交批次组织结果；点击单号展开完整轨迹时间线。' },
  { n: 4, title: '检查更新', body: '未完结的单号可随时「检查更新」，服务端按规则决定新建任务或沿用现有结果，沿用会明确标记。' },
] as const

function jump(id: string) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <section class="guide-page">
    <!-- 左侧目录（对齐竞品帮助中心）：桌面端固定，移动端折叠为顶部条 -->
    <aside class="toc" aria-label="页面目录">
      <p class="toc-cap">使用指南</p>
      <nav>
        <button v-for="s in SECTIONS" :key="s.id" type="button" @click="jump(s.id)">
          {{ s.label }}
        </button>
      </nav>
    </aside>

    <article class="guide-body">
      <h1 class="page-title">{{ t('guide.title') }}</h1>
      <p class="page-sub">{{ t('guide.sub') }}</p>

      <h2 id="quick-start" class="sec-title">快速开始</h2>
      <ol class="steps">
        <li v-for="st in STEPS" :key="st.n" class="card step">
          <span class="step-n" aria-hidden="true">{{ st.n }}</span>
          <div>
            <h3>{{ st.title }}</h3>
            <p>{{ st.body }}</p>
          </div>
        </li>
      </ol>

      <h2 id="input" class="sec-title">{{ t('guide.input_title') }}</h2>
      <div class="card"><p>{{ t('guide.input_body') }}</p></div>

      <h2 id="fee" class="sec-title">{{ t('guide.fee_title') }}</h2>
      <div class="card"><p>{{ t('guide.fee_body') }}</p></div>

      <h2 id="results" class="sec-title">{{ t('guide.results_title') }}</h2>
      <div class="card"><p>{{ t('guide.results_body') }}</p></div>

      <h2 id="refresh" class="sec-title">{{ t('guide.refresh_title') }}</h2>
      <div class="card"><p>{{ t('guide.refresh_body') }}</p></div>

      <h2 id="account" class="sec-title">{{ t('guide.account_title') }}</h2>
      <div class="card"><p>{{ t('guide.account_body') }}</p></div>

      <h2 id="anomaly" class="sec-title">{{ t('guide.anomaly_title') }}</h2>
      <div class="card"><p>{{ t('guide.anomaly_body') }}</p></div>

      <div class="guide-foot">
        <RouterLink class="btn" to="/register">免费注册</RouterLink>
        <RouterLink class="btn ghost" to="/products">了解产品能力</RouterLink>
      </div>
    </article>
  </section>
</template>

<style scoped>
.guide-page {
  display: grid; grid-template-columns: 200px minmax(0, 1fr);
  gap: 28px; max-width: 980px; margin: 0 auto;
}
.toc { position: sticky; top: 84px; align-self: start; }
.toc-cap { font-size: 12px; color: var(--fg-soft); letter-spacing: 0.5px; margin: 0 0 8px; }
.toc nav { display: flex; flex-direction: column; gap: 2px; }
.toc nav button {
  text-align: left; background: none; border: none; font: inherit;
  color: var(--fg-soft); padding: 7px 12px; border-radius: var(--radius-ctl);
  cursor: pointer; transition: background var(--dur) ease-out, color var(--dur) ease-out;
}
.toc nav button:hover { background: var(--bg); color: var(--fg); }
.sec-title { font-size: 18px; margin: 30px 0 12px; scroll-margin-top: 84px; }
.steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
.step { display: flex; gap: 14px; align-items: flex-start; margin-bottom: 0; }
.step-n {
  flex-shrink: 0; width: 30px; height: 30px; border-radius: 999px;
  background: var(--fg); color: #fff; font-weight: 700; font-size: 15px;
  display: flex; align-items: center; justify-content: center;
}
.step h3 { margin: 0 0 4px; font-size: 16px; }
.step p { margin: 0; color: var(--fg-soft); font-size: 14px; text-wrap: pretty; }
.guide-foot { display: flex; gap: 12px; margin-top: 30px; }
@media (max-width: 860px) {
  .guide-page { grid-template-columns: 1fr; gap: 16px; }
  .toc { position: static; }
  .toc nav { flex-direction: row; flex-wrap: wrap; }
}
</style>
