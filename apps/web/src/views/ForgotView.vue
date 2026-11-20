<script setup lang="ts">
// 忘记密码（04 §2.1 公共区）：本版人工通道，不暴露内部流程。
import { useRouter } from 'vue-router'
import { t } from '../i18n'
const router = useRouter()
</script>

<template>
  <section class="about">
    <h1 class="page-title">{{ t('forgot.title') }}</h1>
    <div class="card">
      <p>{{ t('forgot.body') }}</p>
      <p class="hint">{{ t('forgot.hint') }}</p>
      <button class="btn ghost" @click="router.push({ name: 'login' })">{{ t('forgot.back') }}</button>
    </div>
  </section>
</template>

<style scoped>
.about { max-width: 560px; margin: 0 auto; }
</style>
