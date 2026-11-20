<template>
  <section class="landing">
    <div class="hero">
      <p class="pill">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
          <path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11Z" /><circle cx="12" cy="10" r="2.5" />
        </svg>
        开放注册，审核通过即送 <strong>500</strong> 积分
      </p>
      <h1>{{ t('home.hero_title') }}<br /><span class="sub-line">{{ t('home.hero_sub') }}</span></h1>
      <p class="lede">
        {{ t('home.lede') }}
      </p>
      <div class="cta">
        <RouterLink class="btn lg" to="/submit">{{ t('home.cta_start') }}</RouterLink>
        <RouterLink class="btn lg ghost" to="/register">免费注册</RouterLink>
      </div>
      <p class="hint micro">{{ t('home.logged_in_hint') }}</p>
    </div>

    <div class="features">
      <div v-for="f in FEATURES" :key="f.icon" class="feat">
        <div class="feat-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <template v-if="f.icon === 'batch'">
              <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
            </template>
            <template v-else-if="f.icon === 'live'">
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
        <RouterLink to="/products">{{ t('home.foot_products') }}</RouterLink>
        <RouterLink to="/pricing">{{ t('home.foot_pricing') }}</RouterLink>
        <RouterLink to="/guide">{{ t('home.foot_guide') }}</RouterLink>
        <RouterLink to="/trial">{{ t('nav.trial') }}</RouterLink>
      </nav>
      <p class="hint">{{ t('home.foot_note') }}</p>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { t } from '../i18n'

// 未登录首页 = 纯产品介绍页（P15，对齐竞品）：不放查询功能；
// 「开始使用」进入提交路径（未登录由路由守卫带到登录页并回跳）。
// icon 为稳定键，分支不随语言切换变化；title/desc 走 i18n 词典。
const FEATURES = computed(() => [
  {
    icon: 'batch',
    title: t('home.feat.batch'),
    desc: t('home.feat.batch_desc'),
  },
  {
    icon: 'live',
    title: t('home.feat.live'),
    desc: t('home.feat.live_desc'),
  },
  {
    icon: 'history',
    title: t('home.feat.history'),
    desc: t('home.feat.history_desc'),
  },
])
</script>

<style scoped>
.landing { max-width: 900px; margin: 0 auto; text-align: center; }
.hero { padding: 48px 0 24px; }
/* 公告 pill（对齐竞品顶部徽章）：浅底圆角胶囊，强调赠送积分 */
.pill {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--brand-soft); color: var(--brand-strong);
  border: 1px solid var(--brand-line); border-radius: 999px;
  padding: 6px 16px; font-size: 14px; font-weight: 500; margin: 0 0 22px;
}
.pill strong { font-weight: 700; }
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
.foot nav { display: flex; gap: 20px; justify-content: center; margin-bottom: 8px; flex-wrap: wrap; }
.foot nav a { color: var(--fg-soft); text-decoration: none; font-size: 14px; }
.foot nav a:hover { color: var(--brand); }
</style>
