<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

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

function handleFileChange(key, event) {
  const [file] = event.target.files
  selectedFiles[key] = file || null
}

function formatFileSize(file) {
  if (!file) return ''
  if (file.size < 1024 * 1024) return `${(file.size / 1024).toFixed(1)} KB`
  return `${(file.size / 1024 / 1024).toFixed(2)} MB`
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
})
</script>

<template>
  <div>
    <section class="payroll-hero">
      <div class="container payroll-hero-grid">
        <div>
          <p class="eyebrow">CREATOR TOOLS</p>
          <h1>兼职薪资计算</h1>
          <p>
            先把主播排班、场控排班、试播间排班和主播数据上传到后台。当前版本先打通上传与下载闭环，
            下一步会接入和 work01 薪资项目一致的真实计算规则。
          </p>
        </div>
        <div class="payroll-hero-card">
          <span>STEP 01</span>
          <strong>上传 → 后台生成测试文档 → 下载</strong>
          <p>这一步用于确认网站功能链路可用，真实薪资算法会在下一阶段接入。</p>
          <div class="payroll-api-status" :class="`is-${apiHealth.status}`">
            <b>{{ apiHealthLabel }}</b>
            <small>{{ apiHealth.message }}</small>
          </div>
        </div>
      </div>
    </section>

    <section class="section container payroll-workspace">
      <form class="payroll-panel" @submit.prevent="submitPayrollJob">
        <div class="payroll-panel-heading">
          <div>
            <p class="eyebrow">UPLOAD FILES</p>
            <h2>上传计算薪资所需信息</h2>
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

      <aside class="payroll-result-card">
        <p class="eyebrow">RESULT</p>
        <h2>计算结果</h2>

        <div v-if="!job" class="payroll-empty">
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
    </section>
  </div>
</template>
