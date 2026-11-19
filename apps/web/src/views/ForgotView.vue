<script setup lang="ts">
// 忘记密码（04 §2.1 公共区）：本版人工通道，不暴露内部流程。
import { useRouter } from 'vue-router'
const router = useRouter()
</script>

<template>
  <section class="about">
    <h1 class="page-title">找回密码</h1>
    <div class="card">
      <p>密码自助重置通道即将开放。当前请联系支持，提供注册邮箱，人工验证后为你重置。</p>
      <p class="hint">重置成功后请重新登录；会话安全不受影响。</p>
      <button class="btn ghost" @click="router.push({ name: 'login' })">返回登录</button>
    </div>
  </section>
</template>

<style scoped>
.about { max-width: 560px; margin: 0 auto; }
</style>
