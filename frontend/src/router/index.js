import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ProductsView from '../views/ProductsView.vue'
import FeaturesView from '../views/FeaturesView.vue'
import BrandView from '../views/BrandView.vue'
import ContactView from '../views/ContactView.vue'

const routes = [
  { path: '/', name: 'home', component: HomeView, meta: { title: '首页' } },
  { path: '/products', name: 'products', component: ProductsView, meta: { title: '产品' } },
  { path: '/features', name: 'features', component: FeaturesView, meta: { title: '功能' } },
  { path: '/brand', name: 'brand', component: BrandView, meta: { title: '品牌' } },
  { path: '/contact', name: 'contact', component: ContactView, meta: { title: '联系我们' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = `${to.meta.title}｜造物者 CREATOR`
})

export default router
