<script setup lang="ts">
import { useRouter } from 'vue-router'
import { t } from '../i18n'
const router = useRouter()
</script>

<template>
  <section class="nf">
    <h1 class="page-title">{{ t('nf.title') }}</h1>
    <p class="page-sub">{{ t('nf.sub') }}</p>
    <button class="btn" @click="router.push({ name: 'home' })">{{ t('nf.back') }}</button>
  </section>
</template>
