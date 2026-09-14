<script setup>
import { ArrowUpRight, Check } from '@lucide/vue'
import { knowledgeDate } from '../api/knowledge'
defineProps({ article: { type: Object, required: true } })
</script>

<template>
  <article class="kb-result">
    <div class="kb-meta"><span>{{ article.category.name }}</span><span>{{ article.platform }}</span><span class="kb-approved"><Check :size="13" /> 已审核</span></div>
    <h2><RouterLink :to="`/library/${article.id}`">{{ article.title }}</RouterLink></h2>
    <p class="kb-answer">{{ article.summary }}</p>
    <ol class="kb-steps"><li v-for="(step, index) in article.steps" :key="index">{{ step }}</li></ol>
    <div class="kb-result-bottom">
      <span>V{{ article.version }} <span aria-hidden="true">·</span> 更新于 {{ knowledgeDate(article.updated_at) }}</span>
      <RouterLink :to="`/library/${article.id}`" class="kb-link">查看完整教程 <ArrowUpRight :size="17" /></RouterLink>
    </div>
  </article>
</template>
