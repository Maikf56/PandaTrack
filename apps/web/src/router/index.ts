import { createRouter, createWebHistory } from 'vue-router'
import { loadSession } from '../composables/session'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // 公共区（04 §2.1 八路由）
    { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
    // 注册（P16）：开放注册 + 管理员审核后才能登录
    { path: '/register', name: 'register', component: () => import('../views/RegisterView.vue') },
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
    // 结果三级导航（P15）：第一级查询组 → 第二级组内批次 → 第三级批次单号
    { path: '/results', name: 'results', component: () => import('../views/ResultsView.vue'), meta: { auth: true } },
    {
      path: '/results/group/:id',
      name: 'group-batches',
      component: () => import('../views/GroupBatchesView.vue'),
      meta: { auth: true },
    },
    {
      path: '/results/batch/:id',
      name: 'batch-trackings',
      component: () => import('../views/BatchTrackingsView.vue'),
      meta: { auth: true },
    },
    {
      path: '/results/:id',
      name: 'tracking-detail',
      component: () => import('../views/TrackingDetailView.vue'),
      meta: { auth: true },
    },
    { path: '/wallet', name: 'wallet', component: () => import('../views/WalletView.vue'), meta: { auth: true } },
    // 次要页面（04 §5.8-5.12）+ 邀请好友（P15）
    { path: '/imports', name: 'imports', component: () => import('../views/ImportsView.vue'), meta: { auth: true } },
    { path: '/exports', name: 'exports', component: () => import('../views/ExportsView.vue'), meta: { auth: true } },
    { path: '/stats', name: 'stats', component: () => import('../views/StatsView.vue'), meta: { auth: true } },
    { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { auth: true } },
    { path: '/invite', name: 'invite', component: () => import('../views/InviteView.vue'), meta: { auth: true } },
    // 合并/下线的旧路由 → 重定向（P15：提交记录并入积分流水；组页并入结果列表）
    { path: '/submissions', redirect: '/wallet' },
    { path: '/groups', redirect: '/results' },
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
