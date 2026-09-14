import { createRouter, createWebHistory } from 'vue-router'
import KnowledgeView from '../views/KnowledgeView.vue'
import KnowledgeDetailView from '../views/KnowledgeDetailView.vue'
import FeaturesView from '../views/FeaturesView.vue'
import LiveMonitorView from '../views/LiveMonitorView.vue'
import AuthView from '../views/AuthView.vue'
import { loadAuthSession } from '../auth'

const routes = [
  { path: '/login', name: 'login', component: AuthView, meta: { title: '登录', publicAuth: true, authMode: 'login' } },
  { path: '/register', name: 'register', component: AuthView, meta: { title: '注册', publicAuth: true, authMode: 'register' } },
  {
    path: '/recover-account',
    name: 'recover-account',
    component: AuthView,
    meta: { title: '找回账号', publicAuth: true, authMode: 'recoverAccount' },
  },
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: AuthView,
    meta: { title: '忘记密码', publicAuth: true, authMode: 'forgotPassword' },
  },
  {
    path: '/reset-password/:uid/:token',
    name: 'reset-password',
    component: AuthView,
    meta: { title: '重置密码', publicAuth: true, authMode: 'resetPassword' },
  },
  { path: '/', name: 'home', component: KnowledgeView, meta: { title: '首页', knowledge: true } },
  { path: '/library', name: 'library', component: KnowledgeView, meta: { title: '文档库', knowledge: true } },
  { path: '/library/:id', name: 'knowledge-detail', component: KnowledgeDetailView, meta: { title: '完整教程', knowledge: true } },
  { path: '/features', name: 'features', component: FeaturesView, meta: { title: '工具库' } },
  { path: '/features/live-monitor', name: 'live-monitor', component: LiveMonitorView, meta: { title: '直播监控' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const user = await loadAuthSession()
  if (to.meta.publicAuth) {
    return user ? { path: '/' } : true
  }
  if (!user) {
    return {
      path: '/login',
      query: to.fullPath === '/' ? {} : { next: to.fullPath },
    }
  }
  return true
})

router.afterEach((to) => {
  document.title = `${to.meta.title}｜造物者直播间知识中心`
})

export default router
