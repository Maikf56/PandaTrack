<script setup lang="ts">
import { ref } from 'vue'

// 申请试用（04 §2.1 公共区）：提交最少必要信息，人工开通。
// 本版暂无公开试用申请端点，先记录意向提示（不发送第三方）。
const email = ref('')
const note = ref('')
const sent = ref(false)

function submit() {
  if (!email.value.includes('@')) return
  sent.value = true
}
</script>

<template>
  <section class="about">
    <h1 class="page-title">申请试用</h1>
    <p class="page-sub">提交最少必要信息，人工开通试用额度。</p>

    <div v-if="sent" class="ok-box" role="status">
      已收到你的申请意向。我们将通过邮箱与你联系并开通试用；请留意收件箱。
    </div>
    <div v-else class="card">
      <form @submit.prevent="submit">
        <label for="trial-email">联系邮箱</label>
        <input id="trial-email" v-model="email" type="email" required autocomplete="email" />
        <label for="trial-note">使用场景（选填）</label>
        <textarea id="trial-note" v-model="note" style="min-height: 90px"
          placeholder="例如：每日约 XXX 个单号的查询需求"></textarea>
        <p class="hint">仅用于开通评估，不会用于其他用途或发送给第三方。</p>
        <button class="btn" type="submit">提交申请</button>
      </form>
    </div>
  </section>
</template>

<style scoped>
.about { max-width: 560px; margin: 0 auto; }
label { display: block; font-weight: 600; margin: 14px 0 6px; }
</style>
