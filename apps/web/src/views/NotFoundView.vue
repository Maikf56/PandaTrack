<script setup lang="ts">
import { useRouter } from 'vue-router'
const router = useRouter()
</script>

<template>
  <section class="nf">
    <h1 class="page-title">页面不存在</h1>
    <p class="page-sub">你要访问的页面不存在或已被移动。</p>
    <button class="btn" @click="router.push({ name: 'home' })">返回首页</button>
  </section>
</template>
