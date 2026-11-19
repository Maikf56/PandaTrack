import { createRouter, createWebHistory } from 'vue-router'
import { adminSession, api, can, type AdminMe } from '../api/client'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    { path: '/', name: 'customers', component: () => import('../views/CustomersView.vue'), meta: { auth: true, perm: 'customers:read' } },
    { path: '/billing', name: 'billing', component: () => import('../views/BillingView.vue'), meta: { auth: true, perm: 'billing:read' } },
    { path: '/providers', name: 'providers', component: () => import('../views/ProvidersView.vue'), meta: { auth: true, perm: 'providers:read' } },
    { path: '/audit', name: 'audit', component: () => import('../views/AuditView.vue'), meta: { auth: true, perm: 'audit:read' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

// 会话守卫：未登录访问 → 跳登录（03 §3.1 短时效独立会话）；
// 已登录但角色无该页权限 → 回首页（RBAC 03 §2，前端可见性控制）
router.beforeEach(async (to) => {
  if (!to.meta.auth) return true
  if (!adminSession.me) {
    try {
      const me = await api.post<AdminMe>('/api/v1/admin/auth/whoami')
      adminSession.me = me
    } catch {
      return { name: 'login', query: { next: to.fullPath } }
    }
  }
  const perm = to.meta.perm as string | undefined
  if (perm && !can(perm)) return { name: 'customers' }
  return true
})

export default router
