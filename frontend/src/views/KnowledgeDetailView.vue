<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, ArrowRight, Check, BookOpen, ExternalLink, RotateCw } from '@lucide/vue'
import { knowledgeRequest, knowledgeDate } from '../api/knowledge'

const route = useRoute()
const article = ref(null)
const busy = ref(true)
const error = ref('')
let controller
async function load() {
  controller?.abort()
  const pending = new AbortController()
  controller = pending
  busy.value = true
  error.value = ''
  article.value = null
  try {
    const next = await knowledgeRequest(`articles/${route.params.id}/`, {}, pending.signal)
    if (pending.signal.aborted) return
    article.value = next
    document.title = `${next.title}｜造物者直播间知识中心`
  } catch (err) { if (!pending.signal.aborted) error.value = err.message }
  finally { if (!pending.signal.aborted) busy.value = false }
}
watch(() => route.params.id, load, { immediate: true })
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="kb-page kb-detail">
    <RouterLink to="/library" class="kb-link kb-back"><ArrowLeft :size="16" /> 返回文档库</RouterLink>
    <p v-if="busy" class="kb-empty" role="status">正在加载教程…</p>
    <div v-else-if="error" class="kb-empty" role="alert"><BookOpen :size="30" /><h1>暂时无法查看教程</h1><p>{{ error }}</p><button class="kb-link" @click="load"><RotateCw :size="16" /> 重新加载</button></div>
    <article v-else-if="article">
      <div class="kb-meta"><RouterLink :to="{ path: '/library', query: { category: article.category.id } }">{{ article.category.name }}</RouterLink><span>{{ article.platform }}</span><span class="kb-approved"><Check :size="13" /> 已审核</span></div>
      <h1>{{ article.title }}</h1>
      <p class="kb-muted">版本 V{{ article.version }} <span aria-hidden="true">·</span> 更新于 {{ knowledgeDate(article.updated_at) }}</p>
      <p class="kb-detail-summary">{{ article.summary }}</p>
      <section class="kb-quick"><h2>快速处理</h2><ol class="kb-steps"><li v-for="(step, index) in article.steps" :key="index">{{ step }}</li></ol></section>
      <section class="kb-tutorial"><h2>完整教程</h2><p v-for="(paragraph, index) in article.body.split(/\n\s*\n/)" :key="index">{{ paragraph }}</p></section>
      <RouterLink v-if="article.tool_path" :to="article.tool_path" class="kb-link kb-related-tool"><ExternalLink :size="17" /> 打开相关工具</RouterLink>
      <section v-if="article.related.length" class="kb-related"><h2>相关教程</h2><RouterLink v-for="item in article.related" :key="item.id" :to="`/library/${item.id}`" class="kb-related-link">{{ item.title }}<ArrowRight :size="17" /></RouterLink></section>
    </article>
  </div>
</template>
