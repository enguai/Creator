import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ProductsView from '../views/ProductsView.vue'
import ProductDetailView from '../views/ProductDetailView.vue'
import FeaturesView from '../views/FeaturesView.vue'
import BrandView from '../views/BrandView.vue'
import ContactView from '../views/ContactView.vue'

const routes = [
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
