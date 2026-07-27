import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ProductsView from '../views/ProductsView.vue'
import ProductDetailView from '../views/ProductDetailView.vue'
import FeaturesView from '../views/FeaturesView.vue'
import LiveMonitorView from '../views/LiveMonitorView.vue'
import BrandView from '../views/BrandView.vue'
import ContactView from '../views/ContactView.vue'
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
  { path: '/', name: 'home', component: HomeView, meta: { title: '首页' } },
  { path: '/products', name: 'products', component: ProductsView, meta: { title: '产品' } },
  {
    path: '/products/camellia',
    name: 'camellia-product',
    component: ProductDetailView,
    props: { productId: 'camellia' },
    meta: { title: '山茶花软膜' },
  },
  {
    path: '/products/polishing',
    name: 'polishing-product',
    component: ProductDetailView,
    props: { productId: 'polishing' },
    meta: { title: '小气泡抛光面膜' },
  },
  {
    path: '/products/agate-eye',
    name: 'agate-eye-product',
    component: ProductDetailView,
    props: { productId: 'agate-eye' },
    meta: { title: '冰玛瑙眼膜' },
  },
  { path: '/features', name: 'features', component: FeaturesView, meta: { title: '工具库' } },
  { path: '/features/live-monitor', name: 'live-monitor', component: LiveMonitorView, meta: { title: '直播监控' } },
  { path: '/brand', name: 'brand', component: BrandView, meta: { title: '品牌' } },
  { path: '/contact', name: 'contact', component: ContactView, meta: { title: '联系我们' } },
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
  document.title = `${to.meta.title}｜造物者 CREATOR`
})

export default router
