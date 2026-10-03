<script setup>
import { LogOut } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import logo from '../assets/images/creator-logo.jpg'
import { signOut, useAuth } from '../auth'

const route = useRoute()
const router = useRouter()
const { currentUser } = useAuth()
const menuOpen = ref(false)
const lastHomeQuery = ref({})
const navItems = [
  { label: '首页', to: '/' },
  { label: '文档库', to: '/library' },
  { label: '工具库', to: '/features' },
]

function readLastHomeQuery() {
  try {
    const saved = JSON.parse(sessionStorage.getItem('creator.knowledge.last-home-query') || '{}')
    return saved && typeof saved === 'object' ? saved : {}
  } catch {
    return {}
  }
}

function rememberHomeQuery(query) {
  const allowed = ['q', 'mode', 'task', 'category', 'platform', 'page']
  const saved = Object.fromEntries(allowed
    .filter(key => query[key])
    .map(key => [key, query[key]]))
  lastHomeQuery.value = saved
  try { sessionStorage.setItem('creator.knowledge.last-home-query', JSON.stringify(saved)) } catch { /* Session history is optional. */ }
}

lastHomeQuery.value = readLastHomeQuery()
watch(() => route.fullPath, () => {
  menuOpen.value = false
  if (route.path === '/' && route.query.q) rememberHomeQuery(route.query)
  if (route.path === '/' && !route.query.q) {
    lastHomeQuery.value = {}
    try { sessionStorage.removeItem('creator.knowledge.last-home-query') } catch { /* Session history is optional. */ }
  }
})

const homeTarget = computed(() => route.path === '/'
  ? { path: '/', query: route.query }
  : Object.keys(lastHomeQuery.value).length
    ? { path: '/', query: lastHomeQuery.value }
    : '/')

async function logout() {
  await signOut()
  await router.replace('/login')
}
</script>

<template>
  <header class="site-header">
    <div class="header-inner container">
      <RouterLink :to="homeTarget" class="brand" aria-label="造物者首页">
        <span class="brand-logo"><img :src="logo" alt="造物者" /></span>
        <span class="brand-en">知识中心</span>
      </RouterLink>
      <button class="menu-toggle" type="button" :aria-expanded="menuOpen" aria-label="打开导航" @click="menuOpen = !menuOpen">
        <span></span><span></span>
      </button>
      <nav class="nav" :class="{ open: menuOpen }" aria-label="主导航">
        <RouterLink v-for="item in navItems" :key="item.to" :to="item.to === '/' ? homeTarget : item.to" class="nav-link" :class="{ active: item.to !== '/' && route.path.startsWith(item.to) }" exact-active-class="active">
          {{ item.label }}
        </RouterLink>
        <div v-if="currentUser" class="header-account">
          <span>{{ currentUser.username }}</span>
          <button type="button" title="退出登录" @click="logout">
            <LogOut :size="17" aria-hidden="true" />
            退出
          </button>
        </div>
      </nav>
    </div>
  </header>
</template>
