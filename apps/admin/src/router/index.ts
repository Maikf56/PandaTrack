import { createRouter, createWebHistory } from 'vue-router'
import { adminSession, api, type AdminMe } from '../api/client'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    { path: '/', name: 'customers', component: () => import('../views/CustomersView.vue'), meta: { auth: true } },
    { path: '/billing', name: 'billing', component: () => import('../views/BillingView.vue'), meta: { auth: true } },
    { path: '/providers', name: 'providers', component: () => import('../views/ProvidersView.vue'), meta: { auth: true } },
    { path: '/audit', name: 'audit', component: () => import('../views/AuditView.vue'), meta: { auth: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

// 会话守卫：未登录访问 → 跳登录（03 §3.1 短时效独立会话）
router.beforeEach(async (to) => {
  if (!to.meta.auth) return true
  if (adminSession.me) return true
  try {
    const me = await api.post<AdminMe>('/api/v1/admin/auth/whoami')
    adminSession.me = me
    return true
  } catch {
    return { name: 'login', query: { next: to.fullPath } }
  }
})

export default router
