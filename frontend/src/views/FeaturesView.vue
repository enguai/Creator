<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { checkFormAutomationHealth, createFormAutomationJob, getFormAutomationJob } from '../api/forms'
import { checkPayrollHealth, createPayrollJob, getPayrollJob } from '../api/payroll'

const payrollFiles = [
  {
    key: 'host_schedule',
    label: '主播排班表',
    hint: '上传主播本周排班文件，后续用于识别主播出勤与班次。',
  },
  {
    key: 'controller_schedule',
    label: '场控排班表',
    hint: '上传场控本周排班文件，后续用于识别场控时段、双岗小时等信息。',
  },
  {
    key: 'trial_schedule',
    label: '试播间排班表',
    hint: '上传试播间安排文件，后续用于识别试播人员与试播时长。',
  },
  {
    key: 'host_data',
    label: '主播数据',
    hint: '上传主播数据表，后续用于读取直播时长、消耗、ROI 等数据。',
  },
]

const roomTypes = [
  { value: 'general', label: '暂不区分直播间' },
  { value: 'z4-neck', label: 'Z4 颈膜直播间' },
  { value: 'z2-eye', label: 'Z2 眼膜直播间' },
  { value: 'z3-polish', label: 'Z3 抛光直播间' },
]

const formAutomationTypes = {
  expense: {
    label: '费用报销表',
    templateName: '费用报销模板.xlsx',
    templateUrl: '/templates/费用报销模板.xlsx',
    description: '适合根据购买信息截图和发票文件，自动整理费用报销明细。',
  },
  procurement: {
    label: '采购申请表',
    templateName: '采购申请表模板.xlsx',
    templateUrl: '/templates/采购申请表模板.xlsx',
    description: '适合根据商品参考图和链接清单，自动整理采购申请明细。',
  },
}

const selectedFiles = reactive(
  payrollFiles.reduce((files, item) => {
    files[item.key] = null
    return files
  }, {}),
)

const roomType = ref('general')
const weekStart = ref('')
const weekEnd = ref('')
const isSubmitting = ref(false)
const errorMessage = ref('')
const job = ref(null)
const apiHealth = ref({
  status: 'checking',
  message: '正在连接薪资计算后端...',
})
const automationType = ref('expense')
const automationMessage = ref('')
const automationSubmitted = ref(false)
const automationJob = ref(null)
const automationErrorMessage = ref('')
const isAutomationSubmitting = ref(false)
const formApiHealth = ref({
  status: 'checking',
  message: '正在连接报销表格自动化后端...',
  capabilities: null,
})
const automationFiles = reactive({
  purchaseScreenshots: [],
  invoices: [],
  referenceImages: [],
  linkTxt: null,
})

const canSubmit = computed(() => payrollFiles.every((item) => selectedFiles[item.key]) && !isSubmitting.value)

const statusLabel = computed(() => {
  const labels = {
    pending: '等待计算',
    running: '正在计算',
    success: '计算完成',
    failed: '计算失败',
  }

  return labels[job.value?.status] || '尚未提交'
})

const apiHealthLabel = computed(() => {
  const labels = {
    checking: '正在检测',
    ok: '后端已连接',
    error: '后端未连接',
  }

  return labels[apiHealth.value.status] || '未知状态'
})

const selectedAutomationType = computed(() => formAutomationTypes[automationType.value])

const automationStatusLabel = computed(() => {
  const labels = {
    pending: '等待处理',
    running: '正在处理',
    success: '处理完成',
    failed: '处理失败',
  }

  return labels[automationJob.value?.status] || '尚未提交'
})

const automationSubmitReady = computed(() => {
  if (automationType.value === 'expense') {
    return automationFiles.purchaseScreenshots.length > 0 && automationFiles.invoices.length > 0
  }

  return automationFiles.referenceImages.length > 0 && Boolean(automationFiles.linkTxt)
})

const formAutomationCapabilities = computed(() => formApiHealth.value.capabilities || {})

const formAutomationModeLabel = computed(() => {
  const capabilities = formAutomationCapabilities.value
  if (capabilities.backend === 'codex_worker') {
    return capabilities.worker_token_configured
      ? 'Codex Worker 队列模式 · 等待 Windows Worker 处理'
      : 'Codex Worker 队列模式 · 尚未配置 Worker Token'
  }
  if (!capabilities.work05_generator) return '未检测到 work05 表格生成器'
  if (capabilities.ai_configured) {
    return `work05 兼容管线 · AI 识别已就绪 · ${capabilities.openai_model || '默认模型'}`
  }

  return 'work05 兼容管线 · 未配置 API Key，将生成待人工复核表'
})

const automationSummary = computed(() => automationJob.value?.summary || {})

const automationWarnings = computed(() => (
  Array.isArray(automationSummary.value.warnings) ? automationSummary.value.warnings : []
))

function handleFileChange(key, event) {
  const [file] = event.target.files
  selectedFiles[key] = file || null
}

function formatFileSize(file) {
  if (!file) return ''
  if (file.size < 1024 * 1024) return `${(file.size / 1024).toFixed(1)} KB`
  return `${(file.size / 1024 / 1024).toFixed(2)} MB`
}

function formatFileCount(files) {
  if (!files?.length) return '尚未选择'
  return `${files.length} 个文件`
}

function handleAutomationFolderChange(key, event) {
  automationFiles[key] = Array.from(event.target.files || [])
}

function handleAutomationFileChange(key, event) {
  const [file] = event.target.files || []
  automationFiles[key] = file || null
}

function submitAutomationForm() {
  automationSubmitted.value = true
  automationMessage.value = automationSubmitReady.value ? '' : '请先补齐当前表格类型所需的上传材料。'
}

function wait(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

async function pollJobUntilFinished(jobId) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(1500)
    const latestJob = await getPayrollJob(jobId)
    job.value = latestJob

    if (['success', 'failed'].includes(latestJob.status)) {
      return latestJob
    }
  }

  throw new Error('计算时间较长，请稍后刷新页面或重新提交。')
}

async function pollFormAutomationJobUntilFinished(jobId) {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    await wait(3000)
    const latestJob = await getFormAutomationJob(jobId)
    automationJob.value = latestJob

    if (['success', 'failed'].includes(latestJob.status)) {
      return latestJob
    }
  }

  throw new Error('处理时间较长，请稍后刷新页面或重新提交。')
}

async function submitPayrollJob() {
  errorMessage.value = ''
  job.value = null

  if (!canSubmit.value) {
    errorMessage.value = '请先上传全部四个文件。'
    return
  }

  const formData = new FormData()
  formData.append('room_type', roomType.value)
  if (weekStart.value) formData.append('week_start', weekStart.value)
  if (weekEnd.value) formData.append('week_end', weekEnd.value)

  payrollFiles.forEach((item) => {
    formData.append(item.key, selectedFiles[item.key])
  })

  isSubmitting.value = true

  try {
    const createdJob = await createPayrollJob(formData)
    job.value = createdJob

    if (['pending', 'running'].includes(createdJob.status)) {
      await pollJobUntilFinished(createdJob.id)
    }
  } catch (error) {
    errorMessage.value = error.message || '提交失败，请稍后重试。'
    if (error.payload?.id) {
      job.value = error.payload
    }
  } finally {
    isSubmitting.value = false
  }
}

function downloadResult() {
  if (!job.value?.download_url) return
  window.location.href = new URL(job.value.download_url, window.location.origin).href
}

async function submitAutomationJob() {
  automationSubmitted.value = true
  automationMessage.value = ''
  automationErrorMessage.value = ''
  automationJob.value = null

  if (!automationSubmitReady.value) {
    automationMessage.value = '请先补齐当前表格类型所需的上传材料。'
    return
  }

  const formData = new FormData()
  formData.append('form_type', automationType.value)

  if (automationType.value === 'expense') {
    automationFiles.purchaseScreenshots.forEach((file) => {
      formData.append('purchase_screenshots', file)
    })
    automationFiles.invoices.forEach((file) => {
      formData.append('invoices', file)
    })
  } else {
    automationFiles.referenceImages.forEach((file) => {
      formData.append('reference_images', file)
    })
    formData.append('link_txt', automationFiles.linkTxt)
  }

  isAutomationSubmitting.value = true

  try {
    const createdJob = await createFormAutomationJob(formData)
    automationJob.value = createdJob

    if (['pending', 'running'].includes(createdJob.status)) {
      await pollFormAutomationJobUntilFinished(createdJob.id)
    }
  } catch (error) {
    automationErrorMessage.value = error.message || '提交失败，请稍后重试。'
    if (error.payload?.id) {
      automationJob.value = error.payload
    }
  } finally {
    isAutomationSubmitting.value = false
  }
}

function downloadAutomationResult() {
  if (!automationJob.value?.download_url) return
  window.location.href = new URL(automationJob.value.download_url, window.location.origin).href
}

onMounted(async () => {
  try {
    const health = await checkPayrollHealth()
    apiHealth.value = {
      status: 'ok',
      message: health.message || '薪资计算后端已连接。',
    }
  } catch (error) {
    apiHealth.value = {
      status: 'error',
      message: error.message || '无法连接到薪资计算后端。',
    }
  }

  try {
    const health = await checkFormAutomationHealth()
    formApiHealth.value = {
      status: 'ok',
      message: health.message || '报销表格自动化后端已连接。',
      capabilities: health.capabilities || null,
    }
  } catch (error) {
    formApiHealth.value = {
      status: 'error',
      message: error.message || '无法连接到报销表格自动化后端。',
      capabilities: null,
    }
  }
})

watch(automationType, () => {
  automationMessage.value = ''
  automationSubmitted.value = false
  automationJob.value = null
  automationErrorMessage.value = ''
  automationFiles.purchaseScreenshots = []
  automationFiles.invoices = []
  automationFiles.referenceImages = []
  automationFiles.linkTxt = null
})
</script>

<template>
  <div>
    <section class="features-hero">
      <div class="container features-hero-grid">
        <div>
          <p class="eyebrow">CREATOR TOOLS</p>
          <h1>功能中心</h1>
          <p>
            这里会逐步沉淀造物者直播部门的内部效率工具。当前已规划兼职薪资计算和报销表格自动化，
            后续还可以继续扩展数据统计、排班检查、素材管理等功能。
          </p>
        </div>

        <div class="features-overview-card">
          <span>AVAILABLE NOW</span>
          <ul>
            <li>
              <strong>兼职薪资计算</strong>
              <small>上传排班和主播数据，生成薪资测试文档。</small>
            </li>
            <li>
              <strong>报销表格自动化</strong>
              <small>选择表格类型，下载模板并上传生成材料。</small>
            </li>
          </ul>
        </div>
      </div>
    </section>

    <section class="section container tool-module">
      <div class="tool-module-heading">
        <div>
          <p class="eyebrow">PAYROLL WORKFLOW</p>
          <h2>兼职薪资计算</h2>
          <p>
            先把主播排班、场控排班、试播间排班和主播数据上传到后台。当前版本先打通上传与下载闭环，
            下一步会接入和 work01 薪资项目一致的真实计算规则。
          </p>
        </div>
        <div class="payroll-api-status" :class="`is-${apiHealth.status}`">
          <b>{{ apiHealthLabel }}</b>
          <small>{{ apiHealth.message }}</small>
        </div>
      </div>

      <div class="tool-workspace">
        <form class="tool-panel" @submit.prevent="submitPayrollJob">
          <div class="tool-panel-heading">
            <div>
              <p class="eyebrow">UPLOAD FILES</p>
              <h3>上传计算薪资所需信息</h3>
            </div>
            <small>支持 Excel、CSV、PDF、图片等常见文件格式。</small>
          </div>

          <div class="payroll-options">
            <label>
              <span>选择直播间</span>
              <select v-model="roomType">
                <option v-for="item in roomTypes" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>

            <label>
              <span>薪资计算周期</span>
              <div class="payroll-period-inputs">
                <input v-model="weekStart" type="date" aria-label="薪资计算周期开始日期" />
                <b>—</b>
                <input v-model="weekEnd" type="date" aria-label="薪资计算周期结束日期" />
              </div>
            </label>
          </div>

          <div class="payroll-upload-grid">
            <label v-for="item in payrollFiles" :key="item.key" class="payroll-upload-card">
              <input
                type="file"
                accept=".xlsx,.xls,.csv,.pdf,.png,.jpg,.jpeg,.webp"
                @change="handleFileChange(item.key, $event)"
              />
              <span>{{ item.label }}</span>
              <strong>{{ selectedFiles[item.key]?.name || '点击选择文件' }}</strong>
              <em v-if="selectedFiles[item.key]">{{ formatFileSize(selectedFiles[item.key]) }}</em>
              <p>{{ item.hint }}</p>
            </label>
          </div>

          <div v-if="errorMessage" class="payroll-error-box">
            <strong>提交失败</strong>
            <p>{{ errorMessage }}</p>
            <ul>
              <li>如果提示后端未连接，请先启动 Django：python manage.py runserver 0.0.0.0:8000。</li>
              <li>如果是在阿里云访问，请确认 Nginx 已把 /api/ 代理到 Django 后端。</li>
              <li>如果提示上传过大，请压缩图片或提高 Nginx 的 client_max_body_size。</li>
            </ul>
          </div>

          <div class="payroll-actions">
            <button class="primary-button" type="submit" :disabled="!canSubmit">
              {{ isSubmitting ? '正在提交...' : '提交' }}
            </button>
            <p>当前状态：{{ statusLabel }}</p>
          </div>
        </form>

        <aside class="tool-result-card">
          <p class="eyebrow">RESULT</p>
          <h3>计算结果</h3>

          <div v-if="!job" class="result-empty">
            <span>尚未提交</span>
            <p>上传四个文件后点击提交，后台会生成一个测试薪资文档。</p>
          </div>

          <div v-else class="payroll-job">
            <dl>
              <div>
                <dt>任务编号</dt>
                <dd>{{ job.id }}</dd>
              </div>
              <div>
                <dt>状态</dt>
                <dd>{{ statusLabel }}</dd>
              </div>
              <div v-if="job.week_start || job.week_end">
                <dt>薪资计算周期</dt>
                <dd>{{ job.week_start || '未填写' }} - {{ job.week_end || '未填写' }}</dd>
              </div>
            </dl>

            <p v-if="job.status === 'success'" class="payroll-success">
              测试文档已生成，可以下载到本地查看。
            </p>
            <p v-if="job.status === 'failed'" class="payroll-error">
              {{ job.error_message || '计算失败，请检查上传文件后重试。' }}
            </p>

            <button class="download-button" type="button" :disabled="job.status !== 'success'" @click="downloadResult">
              下载薪资文档
            </button>
          </div>
        </aside>
      </div>
    </section>

    <section class="section container tool-module">
      <div class="tool-module-heading">
        <div>
          <p class="eyebrow">FORM AUTOMATION</p>
          <h2>报销表格自动化</h2>
          <p>
            先选择要生成的表格类型，下载对应模板，再上传本次生成所需的材料。当前已切换为 work05 兼容管线：
            有 AI Key 时自动识别物品信息并生成正式表格，未配置时也会生成带图片、发票附件和待复核提示的表格。
          </p>
        </div>
        <div class="payroll-api-status" :class="`is-${formApiHealth.status}`">
          <b>{{ formApiHealth.status === 'ok' ? '后端已连接' : formApiHealth.status === 'error' ? '后端未连接' : '正在检测' }}</b>
          <small>{{ formApiHealth.message }}</small>
          <small v-if="formApiHealth.status === 'ok'">{{ formAutomationModeLabel }}</small>
        </div>
      </div>

      <div class="tool-workspace">
        <div class="tool-panel">
          <div class="automation-type-switch">
            <button
              v-for="item in Object.entries(formAutomationTypes)"
              :key="item[0]"
              type="button"
              :class="{ active: automationType === item[0] }"
              @click="automationType = item[0]"
            >
              <span>{{ item[1].label }}</span>
              <small>{{ item[1].description }}</small>
            </button>
          </div>

          <div class="automation-template-box">
            <div>
              <span>当前模板</span>
              <strong>{{ selectedAutomationType.templateName }}</strong>
              <p>{{ selectedAutomationType.description }}</p>
            </div>
            <a :href="selectedAutomationType.templateUrl" download>下载模板</a>
          </div>

          <div v-if="automationType === 'procurement'" class="automation-upload-grid">
            <label class="automation-upload-card">
              <input
                type="file"
                webkitdirectory
                directory
                multiple
                @change="handleAutomationFolderChange('referenceImages', $event)"
              />
              <span>参考图文件夹</span>
              <strong>{{ formatFileCount(automationFiles.referenceImages) }}</strong>
              <p>上传商品参考图所在文件夹，后续用于识别物品外观、规格和附件。</p>
            </label>

            <label class="automation-upload-card">
              <input type="file" accept=".txt,text/plain" @change="handleAutomationFileChange('linkTxt', $event)" />
              <span>链接 txt 文件</span>
              <strong>{{ automationFiles.linkTxt?.name || '点击选择 .txt 文件' }}</strong>
              <p>上传商品链接清单，后续用于匹配参考图与采购链接。</p>
            </label>
          </div>

          <div v-else class="automation-upload-grid">
            <label class="automation-upload-card">
              <input
                type="file"
                webkitdirectory
                directory
                multiple
                @change="handleAutomationFolderChange('purchaseScreenshots', $event)"
              />
              <span>购买信息截图文件夹</span>
              <strong>{{ formatFileCount(automationFiles.purchaseScreenshots) }}</strong>
              <p>上传购买记录、订单信息或付款信息截图所在文件夹。</p>
            </label>

            <label class="automation-upload-card">
              <input
                type="file"
                webkitdirectory
                directory
                multiple
                @change="handleAutomationFolderChange('invoices', $event)"
              />
              <span>发票文件夹</span>
              <strong>{{ formatFileCount(automationFiles.invoices) }}</strong>
              <p>上传 PDF 或图片发票所在文件夹，后续会与购买信息逐项匹配。</p>
            </label>
          </div>

          <div class="automation-actions">
            <button type="button" class="secondary-button" :disabled="isAutomationSubmitting" @click="submitAutomationJob">
              {{ isAutomationSubmitting ? '正在提交...' : '提交' }}
            </button>
            <p>{{ automationMessage || `当前状态：${automationStatusLabel}` }}</p>
          </div>

          <div v-if="automationErrorMessage" class="payroll-error-box">
            <strong>提交失败</strong>
            <p>{{ automationErrorMessage }}</p>
            <ul>
              <li>请确认 Django 后端服务已启动。</li>
              <li>如果上传的是文件夹，请确认文件夹内至少包含一个文件。</li>
              <li>如果提示上传过大，请减少文件数量或压缩图片后再试。</li>
            </ul>
          </div>
        </div>

        <aside class="tool-result-card">
          <p class="eyebrow">RESULT</p>
          <h3>计算结果</h3>

          <div class="result-empty" :class="{ 'is-ready': automationJob?.status === 'success' }">
            <span>{{ automationJob?.status === 'success' ? '已生成' : automationSubmitted && automationSubmitReady ? '材料已提交' : '尚未提交' }}</span>
            <p>
              {{
                automationJob?.status === 'success'
                  ? '表格已通过 work05 兼容管线生成，可以下载到本地查看。'
                  : automationSubmitted && automationSubmitReady
                    ? '材料已提交到后台，正在生成表格。'
                  : '选择表格类型并上传对应材料后，后续会在这里生成下载结果。'
              }}
            </p>
          </div>

          <dl class="automation-result-list">
            <div>
              <dt>表格类型</dt>
              <dd>{{ selectedAutomationType.label }}</dd>
            </div>
            <div v-if="automationJob">
              <dt>任务编号</dt>
              <dd>{{ automationJob.id }}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{{ automationStatusLabel }}</dd>
            </div>
            <div v-if="automationJob?.summary?.mode">
              <dt>处理管线</dt>
              <dd>{{ automationJob.summary.mode === 'work05-compatible' ? 'work05 兼容管线' : automationJob.summary.mode }}</dd>
            </div>
            <div v-if="automationJob?.summary">
              <dt>处理方式</dt>
              <dd>
                {{
                  automationSummary.mode === 'codex-skill-worker'
                    ? (automationJob.status === 'success' ? 'Codex Worker 已调用 skill 完成生成' : '等待 Codex Worker 调用 skill 处理')
                    : automationSummary.ai_enabled
                    ? `已启用，成功识别 ${automationSummary.ai_success ?? 0}/${automationSummary.item_count ?? 0} 项`
                    : '未配置 API Key，已生成待人工复核表'
                }}
              </dd>
            </div>
            <div v-if="automationType === 'expense'">
              <dt>已选材料</dt>
              <dd>
                购买截图 {{ automationJob?.asset_counts?.purchase_screenshots ?? automationFiles.purchaseScreenshots.length }} 个，
                发票 {{ automationJob?.asset_counts?.invoices ?? automationFiles.invoices.length }} 个
              </dd>
            </div>
            <div v-else>
              <dt>已选材料</dt>
              <dd>
                参考图 {{ automationJob?.asset_counts?.reference_images ?? automationFiles.referenceImages.length }} 个，
                链接文件 {{ automationJob?.asset_counts?.link_txt ?? (automationFiles.linkTxt ? 1 : 0) }} 个
              </dd>
            </div>
          </dl>

          <div v-if="automationWarnings.length" class="automation-warning-box">
            <strong>识别提示</strong>
            <ul>
              <li v-for="warning in automationWarnings.slice(0, 4)" :key="warning">{{ warning }}</li>
            </ul>
          </div>

          <button
            class="download-button"
            type="button"
            :disabled="automationJob?.status !== 'success'"
            @click="downloadAutomationResult"
          >
            下载生成表格
          </button>
        </aside>
      </div>
    </section>
  </div>
</template>
