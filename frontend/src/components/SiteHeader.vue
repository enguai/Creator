<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import logo from '../assets/images/creator-logo.jpg'

const route = useRoute()
const menuOpen = ref(false)
const navItems = [
  { label: '首页', to: '/' },
  { label: '产品', to: '/products' },
  { label: '工具库', to: '/features' },
  { label: '品牌', to: '/brand' },
  { label: '联系我们', to: '/contact' },
]

watch(() => route.path, () => { menuOpen.value = false })
</script>

<template>
  <header class="site-header">
    <div class="header-inner container">
      <RouterLink to="/" class="brand" aria-label="造物者首页">
        <span class="brand-logo"><img :src="logo" alt="造物者" /></span>
        <span class="brand-en">CREATOR</span>
      </RouterLink>
      <button class="menu-toggle" type="button" :aria-expanded="menuOpen" aria-label="打开导航" @click="menuOpen = !menuOpen">
        <span></span><span></span>
      </button>
      <nav class="nav" :class="{ open: menuOpen }" aria-label="主导航">
        <RouterLink v-for="item in navItems" :key="item.to" :to="item.to" class="nav-link" exact-active-class="active">
          {{ item.label }}
        </RouterLink>
      </nav>
    </div>
  </header>
</template>
