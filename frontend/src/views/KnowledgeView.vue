<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search, ArrowRight, ArrowLeft, ChevronRight, Clock3, X, BookOpen, Cable, Video, Package, CircleAlert, ShieldCheck, GraduationCap, FolderOpen, RotateCw } from '@lucide/vue'
import { useAuth } from '../auth'
import { knowledgeRequest } from '../api/knowledge'
import KnowledgeResult from '../components/KnowledgeResult.vue'

const route = useRoute()
const router = useRouter()
const { currentUser } = useAuth()
const library = computed(() => route.name === 'library')
const input = ref('')
const catalog = ref({ categories: [], common: [], platforms: [] })
const results = ref({ results: [], count: 0, page: 1, pages: 1 })
const busy = ref(true)
const error = ref('')
const searched = computed(() => Boolean(String(route.query.q || '').trim()))
const currentCategory = computed(() => catalog.value.categories.find(c => String(c.id) === route.query.category))
const children = computed(() => catalog.value.categories.filter(c => c.parent_id === (currentCategory.value?.id ?? null)))
const trail = computed(() => {
  const list = []
  let category = currentCategory.value
  const seen = new Set()
  while (category && !seen.has(category.id)) {
    seen.add(category.id)
    list.unshift(category)
    category = catalog.value.categories.find(c => c.id === category.parent_id)
  }
  return list
})
const categoryIcons = [Cable, Video, Package, CircleAlert, ShieldCheck, GraduationCap]
const recentKey = `creator.knowledge.searches.${currentUser.value?.id || currentUser.value?.username}`
const recent = ref([])
try {
  const saved = JSON.parse(localStorage.getItem(recentKey) || '[]')
  if (Array.isArray(saved)) recent.value = saved.filter(x => typeof x === 'string' && x.length <= 200).slice(0, 6)
} catch { /* A restricted browser can still search without local history. */ }

function saveRecent(query) {
  recent.value = [query, ...recent.value.filter(item => item !== query)].slice(0, 6)
  persistRecent()
}
function persistRecent() {
  try { localStorage.setItem(recentKey, JSON.stringify(recent.value)) } catch { /* Storage is optional. */ }
}
function removeRecent(query) {
  recent.value = recent.value.filter(item => item !== query)
  persistRecent()
}
function search(query = input.value) {
  const q = query.trim().slice(0, 200)
  if (!q) return
  saveRecent(q)
  router.push({ path: library.value ? '/library' : '/', query: { ...route.query, q, page: undefined } })
}
function filter(key, value) {
  router.push({ path: library.value ? '/library' : '/', query: { ...route.query, [key]: value || undefined, page: undefined } })
}
let controller
async function load() {
  controller?.abort()
  const pending = new AbortController()
  controller = pending
  busy.value = true
  error.value = ''
  input.value = String(route.query.q || '')
  try {
    const [nextCatalog, nextResults] = await Promise.all([
      knowledgeRequest('catalog/', {}, pending.signal),
      knowledgeRequest('articles/', { q: route.query.q, category: route.query.category, platform: route.query.platform, page: route.query.page }, pending.signal),
    ])
    if (pending.signal.aborted) return
    catalog.value = nextCatalog
    results.value = nextResults
  } catch (err) {
    if (!pending.signal.aborted) error.value = err.message || '连接失败，请检查网络后重试。'
  } finally {
    if (!pending.signal.aborted) busy.value = false
  }
}
watch(() => route.fullPath, load, { immediate: true })
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="kb-page" :class="{ 'kb-is-searching': searched, 'kb-is-library': library }">
    <section class="kb-search-area">
      <template v-if="!library && !searched">
        <h1>造物者直播间知识中心</h1>
        <p class="kb-intro">从开播准备到现场问题，找到经过审核的解决方法。</p>
      </template>
      <template v-else-if="library">
        <div class="kb-page-heading"><BookOpen :size="25" /><h1>文档库</h1></div>
        <p class="kb-intro">按分类浏览直播知识与标准教程。</p>
      </template>
      <h1 v-else class="kb-search-title">知识搜索</h1>
      <form v-if="!library" class="kb-searchbox" role="search" @submit.prevent="search()">
        <Search :size="23" aria-hidden="true" />
        <input v-model="input" aria-label="搜索直播问题" placeholder="遇到什么直播问题？" maxlength="200" type="search" />
        <button v-if="input" type="button" class="kb-icon-button kb-clear" title="清空搜索内容" aria-label="清空搜索内容" @click="input = ''"><X :size="18" /></button>
        <button type="submit" class="kb-search-submit">搜索 <ArrowRight :size="18" /></button>
      </form>
      <div v-if="!library && !searched && recent.length" class="kb-recent">
        <span><Clock3 :size="14" /> 近期搜索</span>
        <div v-for="item in recent" :key="item" class="kb-recent-item"><button type="button" @click="search(item)">{{ item }}</button><button class="kb-icon-button" type="button" :title="`删除搜索记录：${item}`" :aria-label="`删除搜索记录：${item}`" @click="removeRecent(item)"><X :size="13" /></button></div>
      </div>
    </section>

    <div class="kb-content">
      <div v-if="error" class="kb-error" role="alert"><CircleAlert :size="21" /><span>{{ error }}</span><button type="button" class="kb-link" @click="load"><RotateCw :size="16" /> 重试</button></div>
      <template v-else>
        <div v-if="library" class="kb-library-browse">
          <nav class="kb-breadcrumb" aria-label="分类路径"><RouterLink to="/library">全部分类</RouterLink><template v-for="item in trail" :key="item.id"><ChevronRight :size="14" /><RouterLink :to="{ path: '/library', query: { category: item.id } }">{{ item.name }}</RouterLink></template></nav>
          <div v-if="children.length" class="kb-categories">
            <RouterLink v-for="(category, index) in children" :key="category.id" :to="{ path: '/library', query: { category: category.id } }" class="kb-category">
              <component :is="category.parent_id ? FolderOpen : categoryIcons[index % categoryIcons.length]" :size="22" /><span>{{ category.name }}<small>{{ category.count }} 篇教程</small></span><ChevronRight :size="16" />
            </RouterLink>
          </div>
        </div>

        <template v-if="library || searched">
          <div class="kb-results-toolbar">
            <h2>{{ searched ? `“${route.query.q}”的搜索结果` : (currentCategory?.name || '全部教程') }}<small v-if="!busy">{{ results.count }} 篇</small></h2>
            <div class="kb-filters">
              <label v-if="!library"><span class="kb-sr-only">知识分类</span><select :value="route.query.category || ''" @change="filter('category', $event.target.value)"><option value="">全部分类</option><option v-for="category in catalog.categories" :key="category.id" :value="category.id">{{ category.name }}</option></select></label>
              <label><span class="kb-sr-only">直播平台</span><select :value="route.query.platform || ''" @change="filter('platform', $event.target.value)"><option value="">全部平台</option><option v-for="platform in catalog.platforms" :key="platform.id" :value="platform.id">{{ platform.name }}</option></select></label>
            </div>
          </div>
          <div v-if="busy" class="kb-empty" role="status">正在查找知识内容…</div>
          <template v-else-if="results.results.length">
            <KnowledgeResult v-for="article in results.results" :key="article.id" :article="article" />
            <nav v-if="results.pages > 1" class="kb-pagination" aria-label="结果分页"><button type="button" :disabled="results.page <= 1" @click="router.push({ query: { ...route.query, page: results.page - 1 } })"><ArrowLeft :size="16" /> 上一页</button><span>{{ results.page }} / {{ results.pages }}</span><button type="button" :disabled="results.page >= results.pages" @click="router.push({ query: { ...route.query, page: results.page + 1 } })">下一页 <ArrowRight :size="16" /></button></nav>
          </template>
          <div v-else class="kb-empty"><Search :size="30" /><h2>{{ searched ? '暂无相关答案' : '暂无已发布教程' }}</h2><p>{{ searched ? '试试更简短的关键词，或前往文档库浏览。' : '内容审核发布后将在这里显示。' }}</p><RouterLink v-if="searched" to="/library" class="kb-link">浏览文档库 <ArrowRight :size="16" /></RouterLink></div>
        </template>

        <template v-else>
          <section class="kb-common"><div class="kb-section-heading"><h2>常见问题</h2><span>已审核的解决方法</span></div><p v-if="busy" class="kb-muted" role="status">正在加载…</p><div v-else-if="catalog.common.length" class="kb-question-list"><RouterLink v-for="item in catalog.common" :key="item.id" :to="`/library/${item.id}`"><span>{{ item.title }}</span><ArrowRight :size="17" /></RouterLink></div><p v-else class="kb-muted kb-common-empty">暂无已发布的常见问题</p></section>
          <section class="kb-home-library"><div class="kb-section-heading"><h2>从分类开始</h2><RouterLink to="/library" class="kb-link">全部文档 <ArrowRight :size="16" /></RouterLink></div><div class="kb-category-shortcuts"><RouterLink v-for="(category, index) in children" :key="category.id" :to="{ path: '/library', query: { category: category.id } }"><component :is="categoryIcons[index % categoryIcons.length]" :size="21" /><span>{{ category.name }}</span></RouterLink></div></section>
        </template>
      </template>
    </div>
  </div>
</template>
