<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { loadSession } from '../composables/session'
import { splitDraft } from '../logic/draft'

// 首页：粘贴单号即开始（04 §5.1）。前端只做长度/空值保护，不判格式。
const router = useRouter()
const text = ref('')
const draft = computed(() => splitDraft(text.value))
const showEmptyTip = ref(false)

const DRAFT_STORAGE_KEY = 'pt_home_draft'

async function start() {
  if (draft.value.totalLines === 0) {
    showEmptyTip.value = true
    return
  }
  showEmptyTip.value = false
  const me = await loadSession()
  if (!me) {
    // 未登录：保留输入（sessionStorage 草稿），登录成功后回到 /quick（04 §5.1/§5.2）
    sessionStorage.setItem(DRAFT_STORAGE_KEY, text.value)
    router.push({ name: 'login', query: { next: '/quick' } })
    return
  }
  router.push({ name: 'quick' })
}
</script>

<template>
  <section class="hero">
    <h1>查询 USPS 包裹</h1>
    <p class="page-sub">
      粘贴或输入单号，一次完成清洗、计费与受理；结果在后台逐步更新。
    </p>
    <div class="card hero-card">
      <label for="home-numbers" class="field-label">输入 USPS 单号（每行一个）</label>
      <textarea
        id="home-numbers"
        v-model="text"
        class="big mono"
        placeholder="9400 1000 0000 0000 0000 00&#10;支持一次输入多个单号，直接粘贴批量文本"
        @keydown.enter.exact.prevent="start"
      ></textarea>
      <p v-if="showEmptyTip" class="error-box" role="alert">请输入至少一个单号</p>
      <p v-if="draft.totalLines > 0" class="hint" role="status">
        已接收 {{ draft.totalLines }} 行
        <template v-if="draft.overLong.length">；第 {{ draft.overLong.join('、') }} 行超过 100 字符</template>
        <template v-if="draft.overLimit">
          ；超过 35 行将走批量提交路径，上限与计费以服务端响应为准
        </template>
      </p>
      <p class="hint fee-rule">
        费用规则：1 个新单号扣 1 积分，30 天内重复免扣，无效项不扣费。
      </p>
      <div class="hero-actions">
        <button class="btn" @click="start">开始查询</button>
        <RouterLink class="btn ghost" to="/products">查看产品说明</RouterLink>
        <RouterLink class="btn ghost" to="/pricing">积分套餐</RouterLink>
      </div>
      <p class="hint">点击「开始查询」即提交并按规则扣费；提交前无预览或报价步骤。</p>
    </div>
    <div class="card">
      <h3>真实结果原则</h3>
      <ul>
        <li>只展示已取得的真实结果，等待状态不会伪装成已获取轨迹。</li>
        <li>提交后任务在后台继续，关闭页面不会取消查询。</li>
        <li>每次提交的实际扣费在提交结果中返回，余额不做本地计算。</li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.hero { max-width: 760px; margin: 0 auto; }
.hero h1 { font-size: 28px; margin: 0 0 6px; }
.field-label { display: block; font-weight: 600; margin-bottom: 8px; }
.hero-card { border-top: 3px solid var(--brand); }
.fee-rule { font-weight: 500; }
.hero-actions { display: flex; gap: 12px; margin-top: 8px; flex-wrap: wrap; }
</style>
