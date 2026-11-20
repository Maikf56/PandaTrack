<script setup lang="ts">
import { ref } from 'vue'
import { t } from '../i18n'

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
    <h1 class="page-title">{{ t('trial.title') }}</h1>
    <p class="page-sub">{{ t('trial.sub') }}</p>

    <div v-if="sent" class="ok-box" role="status">
      {{ t('trial.sent') }}
    </div>
    <div v-else class="card">
      <form @submit.prevent="submit">
        <label for="trial-email">{{ t('trial.email') }}</label>
        <input id="trial-email" v-model="email" type="email" required autocomplete="email" />
        <label for="trial-note">{{ t('trial.note') }}</label>
        <textarea id="trial-note" v-model="note" style="min-height: 90px"
          :placeholder="t('trial.note_placeholder')"></textarea>
        <p class="hint">{{ t('trial.privacy') }}</p>
        <button class="btn" type="submit">{{ t('trial.submit') }}</button>
      </form>
    </div>
  </section>
</template>

<style scoped>
.about { max-width: 560px; margin: 0 auto; }
label { display: block; font-weight: 600; margin: 14px 0 6px; }
</style>
