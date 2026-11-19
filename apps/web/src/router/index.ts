import { createRouter, createWebHistory } from 'vue-router'
import { loadSession } from '../composables/session'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // 公共区（04 §2.1 八路由）
    { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    { path: '/products', name: 'products', component: () => import('../views/ProductsView.vue') },
    { path: '/pricing', name: 'pricing', component: () => import('../views/PricingView.vue') },
    { path: '/trial', name: 'trial', component: () => import('../views/TrialView.vue') },
    { path: '/forgot', name: 'forgot', component: () => import('../views/ForgotView.vue') },
    {
      path: '/guide',
      name: 'guide',
      component: () => import('../views/GuideView.vue'),
    },
    // 工作台（需登录）
    { path: '/submit', name: 'submit', component: () => import('../views/SubmitView.vue'), meta: { auth: true } },
    { path: '/quick', name: 'quick', component: () => import('../views/QuickView.vue'), meta: { auth: true } },
    { path: '/dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { auth: true } },
    { path: '/results', name: 'results', component: () => import('../views/ResultsView.vue'), meta: { auth: true } },
    { path: '/submissions', name: 'submissions', component: () => import('../views/SubmissionsView.vue'), meta: { auth: true } },
    {
      path: '/results/:id',
      name: 'tracking-detail',
      component: () => import('../views/TrackingDetailView.vue'),
      meta: { auth: true },
    },
    { path: '/wallet', name: 'wallet', component: () => import('../views/WalletView.vue'), meta: { auth: true } },
    // 次要页面（04 §5.8-5.12）
    { path: '/groups', name: 'groups', component: () => import('../views/GroupsView.vue'), meta: { auth: true } },
    { path: '/imports', name: 'imports', component: () => import('../views/ImportsView.vue'), meta: { auth: true } },
    { path: '/exports', name: 'exports', component: () => import('../views/ExportsView.vue'), meta: { auth: true } },
    { path: '/stats', name: 'stats', component: () => import('../views/StatsView.vue'), meta: { auth: true } },
    { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { auth: true } },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('../views/NotFoundView.vue') },
  ],
})

// 会话守卫：未登录访问受保护页 → 跳登录（query.next 带回原路径，04 §5.2）
router.beforeEach(async (to) => {
  if (!to.meta.auth) return true
  const me = await loadSession()
  if (me) return true
  return { name: 'login', query: { next: to.fullPath } }
})

export default router
