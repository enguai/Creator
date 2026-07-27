<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import SiteHeader from './components/SiteHeader.vue'
import SiteFooter from './components/SiteFooter.vue'

const route = useRoute()
const authPage = computed(() => Boolean(route.meta.publicAuth))
</script>

<template>
  <div class="site-shell" :class="{ 'is-auth-page': authPage }">
    <SiteHeader v-if="!authPage" />
    <main :class="{ 'auth-main': authPage }">
      <RouterView />
    </main>
    <SiteFooter v-if="!authPage" />
  </div>
</template>
