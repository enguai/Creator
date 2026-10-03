<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search, ArrowRight, ArrowLeft, ChevronRight, Clock3, X, BookOpen, Cable, Video, Package, CircleAlert, ShieldCheck, GraduationCap, FolderOpen, RotateCw, MessageCircle, Paperclip, Download } from '@lucide/vue'
import { useAuth } from '../auth'
import { knowledgeRequest, knowledgeUpload } from '../api/knowledge'
import KnowledgeResult from '../components/KnowledgeResult.vue'

const route = useRoute()
const router = useRouter()
const { currentUser } = useAuth()
const library = computed(() => route.name === 'library')
const input = ref('')
const mode = ref('local')
const catalog = ref({ categories: [], common: [], platforms: [] })
const results = ref({ results: [], count: 0, page: 1, pages: 1 })
const codexTask = ref(null)
const codexError = ref('')
const selectedFiles = ref([])
const fileInput = ref(null)
const busy = ref(true)
const error = ref('')
const searched = computed(() => Boolean(String(route.query.q || '').trim()))
const codexMode = computed(() => searched.value && route.query.mode === 'codex')
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
function returnHome() {
  try { sessionStorage.removeItem('creator.knowledge.last-home-query') } catch { /* Session history is optional. */ }
  router.replace('/')
}
function clearCodexPoll() {
  if (codexPollTimer) {
    clearTimeout(codexPollTimer)
    codexPollTimer = null
  }
}

let codexPollTimer
const allowedFileExtensions = new Set(['.xlsx', '.xls', '.csv', '.pdf', '.docx', '.png', '.jpg', '.jpeg'])
const maxCodexFiles = 10
const maxCodexFileSize = 50 * 1024 * 1024

function formatFileSize(file) {
  if (file.size < 1024 * 1024) return `${Math.max(1, Math.round(file.size / 1024))} KB`
  return `${(file.size / 1024 / 1024).toFixed(1)} MB`
}

function validateFiles(files) {
  if (files.length > maxCodexFiles) return `一次最多上传 ${maxCodexFiles} 个文件。`
  for (const file of files) {
    const suffix = file.name.includes('.') ? `.${file.name.split('.').pop().toLowerCase()}` : ''
    if (!allowedFileExtensions.has(suffix)) return `不支持“${file.name}”，请上传 Excel、CSV、PDF、Word 或图片。`
    if (!file.size) return `“${file.name}”是空文件，无法上传。`
    if (file.size > maxCodexFileSize) return `“${file.name}”超过 50MB，无法上传。`
  }
  return ''
}

function handleFileChange(event) {
  const files = Array.from(event.target.files || [])
  const message = validateFiles(files)
  if (message) {
    codexError.value = message
    event.target.value = ''
    return
  }
  selectedFiles.value = files
  codexError.value = ''
}

function removeSelectedFile(index) {
  selectedFiles.value = selectedFiles.value.filter((_file, fileIndex) => fileIndex !== index)
  if (fileInput.value) fileInput.value.value = ''
}

async function refreshCodexTask(taskId) {
  clearCodexPoll()
  try {
    const task = await knowledgeRequest(`questions/${taskId}/`)
    codexTask.value = task
    if (task.status === 'pending' || task.status === 'running') {
      codexPollTimer = setTimeout(() => refreshCodexTask(taskId), 1800)
    }
  } catch (err) {
    codexError.value = err.message || '无法查询 Codex 问答任务。'
  }
}

async function startCodex(query, files = selectedFiles.value) {
  clearCodexPoll()
  codexError.value = ''
  codexTask.value = { question: query, status: 'pending', progress: 0, progress_message: '正在提交 Codex 问答任务' }
  try {
    const formData = new FormData()
    formData.append('question', query)
    files.forEach(file => formData.append('files', file))
    const task = await knowledgeUpload('questions/', formData)
    codexTask.value = task
    await router.push({ path: '/', query: { ...route.query, q: query, mode: 'codex', task: task.id, conversation: undefined, page: undefined } })
    refreshCodexTask(task.id)
  } catch (err) {
    codexTask.value = null
    codexError.value = err.message || 'Codex 问答任务提交失败。'
  }
}

async function search(query = input.value) {
  const q = query.trim().slice(0, 200)
  if (!q) return
  saveRecent(q)
  if (mode.value === 'codex' && !library.value) {
    await startCodex(q, selectedFiles.value)
    return
  }
  clearCodexPoll()
  codexTask.value = null
  codexError.value = ''
  router.push({ path: library.value ? '/library' : '/', query: { ...route.query, q, mode: 'local', task: undefined, page: undefined } })
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
  mode.value = route.query.mode === 'codex' ? 'codex' : 'local'
  try {
    if (codexMode.value) {
      if (route.query.task) refreshCodexTask(route.query.task)
      else codexTask.value = null
    } else {
      const nextCatalog = await knowledgeRequest('catalog/', {}, pending.signal)
      if (pending.signal.aborted) return
      catalog.value = nextCatalog
      clearCodexPoll()
      codexTask.value = null
      results.value = await knowledgeRequest('articles/', { q: route.query.q, category: route.query.category, platform: route.query.platform, page: route.query.page }, pending.signal)
    }
  } catch (err) {
    if (!pending.signal.aborted) error.value = err.message || '连接失败，请检查网络后重试。'
  } finally {
    if (!pending.signal.aborted) busy.value = false
  }
}
watch(() => route.fullPath, load, { immediate: true })
onBeforeUnmount(() => {
  controller?.abort()
  clearCodexPoll()
})
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
      <div v-else class="kb-search-heading"><h1 class="kb-search-title">知识搜索</h1><button type="button" class="kb-link" @click="returnHome"><ArrowLeft :size="16" /> 回到首页</button></div>
      <form v-if="!library" class="kb-searchbox" role="search" @submit.prevent="search()">
        <Search :size="23" aria-hidden="true" />
        <input v-model="input" aria-label="搜索直播问题" placeholder="遇到什么直播问题？" maxlength="200" type="search" />
        <button v-if="input" type="button" class="kb-icon-button kb-clear" title="清空搜索内容" aria-label="清空搜索内容" @click="input = ''"><X :size="18" /></button>
        <label class="kb-mode-select"><span>模式</span><select v-model="mode" aria-label="搜索模式"><option value="local">本地</option><option value="codex">Codex</option></select></label>
        <button type="submit" class="kb-search-submit">搜索 <ArrowRight :size="18" /></button>
      </form>
      <div v-if="!library && mode === 'codex'" class="kb-upload-area">
        <div class="kb-upload-heading"><Paperclip :size="17" /><strong>上传数据源文件</strong><span>可选</span></div>
        <p>支持 Excel、CSV、PDF、Word 和图片，最多 10 个文件，单个不超过 50MB。</p>
        <label class="kb-upload-button" for="knowledge-source-files"><Paperclip :size="16" />选择文件</label>
        <input id="knowledge-source-files" ref="fileInput" class="kb-file-input" type="file" multiple accept=".xlsx,.xls,.csv,.pdf,.docx,.png,.jpg,.jpeg" @change="handleFileChange" />
        <p v-if="codexError && !searched" class="kb-upload-error" role="alert">{{ codexError }}</p>
        <ul v-if="selectedFiles.length" class="kb-selected-files">
          <li v-for="(file, index) in selectedFiles" :key="`${file.name}-${file.size}-${index}`"><span>{{ file.name }}<small>{{ formatFileSize(file) }}</small></span><button type="button" class="kb-icon-button" :aria-label="`移除${file.name}`" :title="`移除${file.name}`" @click="removeSelectedFile(index)"><X :size="15" /></button></li>
        </ul>
      </div>
      <p v-if="!library" class="kb-mode-hint">{{ mode === 'codex' ? 'Codex：直接进行 Codex 对话，需要本地 Worker 在线。' : '本地：快速查找已发布教程。' }}</p>
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

        <template v-if="library || (searched && !codexMode)">
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

        <section v-else-if="codexMode" class="kb-codex-answer" aria-live="polite">
          <div class="kb-codex-heading">
            <div><MessageCircle :size="18" /> Codex 回答</div>
          </div>
          <div v-if="codexError" class="kb-error"><CircleAlert :size="21" /><span>{{ codexError }}</span><button type="button" class="kb-link" @click="startCodex(input.trim())"><RotateCw :size="16" /> 重试</button></div>
          <template v-else-if="codexTask?.status === 'pending' || codexTask?.status === 'running'">
            <div class="kb-codex-status"><RotateCw :size="22" class="kb-spin" /><div><h2>正在等待 Codex 回答</h2><p>{{ codexTask.progress_message || '正在提交 Codex 对话任务' }}</p></div><strong>{{ codexTask.progress || 0 }}%</strong></div>
            <p v-if="codexTask.files?.length" class="kb-file-status">已上传 {{ codexTask.files.length }} 个数据源文件，Worker 将先读取文件后分析。</p>
            <div class="kb-progress"><span :style="{ width: `${codexTask.progress || 0}%` }"></span></div>
          </template>
          <div v-else-if="codexTask?.status === 'failed'" class="kb-error"><CircleAlert :size="21" /><span>{{ codexTask.error_message || 'Codex 对话处理失败。' }}</span><button type="button" class="kb-link" @click="startCodex(input.trim())"><RotateCw :size="16" /> 重试</button></div>
          <template v-else-if="codexTask?.status === 'success'">
            <p v-if="codexTask.files?.length" class="kb-file-status">本次分析使用了 {{ codexTask.files.length }} 个数据源文件。</p>
            <div class="kb-codex-text">{{ codexTask.answer }}</div>
            <a v-if="codexTask.result_file?.download_url" class="kb-download" :href="codexTask.result_file.download_url" download><Download :size="16" /> 下载{{ codexTask.result_file.name }}</a>
          </template>
        </section>

        <template v-else>
          <section class="kb-common"><div class="kb-section-heading"><h2>常见问题</h2><span>已审核的解决方法</span></div><p v-if="busy" class="kb-muted" role="status">正在加载…</p><div v-else-if="catalog.common.length" class="kb-question-list"><RouterLink v-for="item in catalog.common" :key="item.id" :to="`/library/${item.id}`"><span>{{ item.title }}</span><ArrowRight :size="17" /></RouterLink></div><p v-else class="kb-muted kb-common-empty">暂无已发布的常见问题</p></section>
          <section class="kb-home-library"><div class="kb-section-heading"><h2>从分类开始</h2><RouterLink to="/library" class="kb-link">全部文档 <ArrowRight :size="16" /></RouterLink></div><div class="kb-category-shortcuts"><RouterLink v-for="(category, index) in children" :key="category.id" :to="{ path: '/library', query: { category: category.id } }"><component :is="categoryIcons[index % categoryIcons.length]" :size="21" /><span>{{ category.name }}</span></RouterLink></div></section>
        </template>
      </template>
    </div>
  </div>
</template>
