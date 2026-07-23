<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import flvjs from 'flv.js'
import {
  Activity,
  Bell,
  ChartNoAxesCombined,
  ChevronDown,
  Download,
  ExternalLink,
  Eye,
  Plus,
  RefreshCw,
  Save,
  Settings,
  Square,
  Trash2,
  Video,
  Wifi,
} from '@lucide/vue'
import LiveAudienceChart from '../components/LiveAudienceChart.vue'
import {
  deleteMonitorLog,
  getMonitorHealth,
  getMonitorState,
  monitorLogExportUrl,
  refreshMonitorStream,
  saveMonitorConfig,
  startMonitor,
  stopMonitor,
} from '../api/liveMonitor'

const tabs = [
  { id: 'monitor', label: '实时监控', icon: Video },
  { id: 'config', label: '告警配置', icon: Bell },
  { id: 'logs', label: '监控日志', icon: ChartNoAxesCombined },
]
const intervals = [5, 15, 30, 60]
const activeTab = ref('monitor')
const douyinId = ref('')
const monitors = ref([])
const logs = ref([])
const serviceOnline = ref(false)
const loading = ref(true)
const submitting = ref(false)
const actionId = ref('')
const errorMessage = ref('')
const notice = ref('')
const expandedLogs = reactive(new Set())
const monitorIntervals = reactive({})
const logIntervals = reactive({})
const configDrafts = reactive({})
const configDirty = reactive({})
const playerErrors = reactive({})
const players = new Map()
let pollTimer = null
let noticeTimer = null

const activeCount = computed(() => monitors.value.length)
const warningCount = computed(() => monitors.value.filter((item) => item.status === 'warning').length)

function showNotice(message) {
  notice.value = message
  window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 2800)
}

function formatCount(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatDate(value) {
  if (!value) return '进行中'
  const date = new Date(value)
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`
}

function formatDuration(startedAt, endedAt = null) {
  const seconds = Math.max(0, Math.floor(((endedAt || Date.now()) - startedAt) / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const rest = seconds % 60
  return `${hours ? `${hours}小时 ` : ''}${minutes}分 ${String(rest).padStart(2, '0')}秒`
}

function statusLabel(status) {
  return {
    starting: '正在启动',
    resolving: '正在查找直播间',
    connecting: '正在连接',
    monitoring: '监控中',
    warning: '已触发告警',
    error: '连接异常',
    stopped: '已停止',
  }[status] || status
}

function ruleLabel(config) {
  if (!config?.enabled) return '未开启告警'
  if (config.mode === 'less') return `在线人数少于 ${formatCount(config.threshold)}`
  if (config.mode === 'range') return `在线人数在 ${formatCount(config.min)} - ${formatCount(config.max)} 之间`
  return `在线人数超过 ${formatCount(config.threshold)}`
}

function ensureUiState() {
  monitors.value.forEach((monitor) => {
    if (!monitorIntervals[monitor.id]) monitorIntervals[monitor.id] = 5
    if (!configDrafts[monitor.id] || !configDirty[monitor.id]) {
      configDrafts[monitor.id] = { ...monitor.config }
    }
  })
  logs.value.forEach((log) => {
    if (!logIntervals[log.id]) logIntervals[log.id] = 5
  })
}

async function loadState({ silent = false } = {}) {
  try {
    const state = await getMonitorState()
    monitors.value = state.monitors || []
    logs.value = state.logs || []
    serviceOnline.value = true
    errorMessage.value = ''
    ensureUiState()
    await nextTick()
    syncPlayers()
  } catch (error) {
    serviceOnline.value = false
    if (!silent) errorMessage.value = error.message
  } finally {
    loading.value = false
  }
}

async function submitMonitor() {
  if (!douyinId.value.trim()) {
    errorMessage.value = '请输入抖音号或直播间网址。'
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    await startMonitor(douyinId.value.trim())
    douyinId.value = ''
    showNotice('监控任务已启动')
    await loadState()
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    submitting.value = false
  }
}

async function runAction(id, action, successMessage) {
  actionId.value = id
  errorMessage.value = ''
  try {
    await action(id)
    showNotice(successMessage)
    await loadState()
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    actionId.value = ''
  }
}

async function saveConfig(monitor) {
  configDirty[monitor.id] = true
  await runAction(
    monitor.id,
    (id) => saveMonitorConfig(id, configDrafts[id]),
    '告警配置已保存',
  )
  configDirty[monitor.id] = false
}

async function removeLog(log) {
  if (!window.confirm(`确定删除“${log.roomTitle || log.douyinId}”的监控日志吗？`)) return
  await runAction(log.id, deleteMonitorLog, '监控日志已删除')
}

function toggleLog(id) {
  expandedLogs.has(id) ? expandedLogs.delete(id) : expandedLogs.add(id)
}

function destroyPlayer(id) {
  const current = players.get(id)
  if (!current) return
  try {
    current.player.pause()
    current.player.unload()
    current.player.detachMediaElement()
    current.player.destroy()
  } catch {
    // Player teardown is best-effort when a stream has already disconnected.
  }
  players.delete(id)
}

function syncPlayers() {
  const activeIds = new Set(monitors.value.map((monitor) => monitor.id))
  players.forEach((_value, id) => {
    if (!activeIds.has(id)) destroyPlayer(id)
  })

  monitors.value.forEach((monitor) => {
    if (!monitor.videoReady || !monitor.streamUrl) return
    const video = document.querySelector(`[data-monitor-video="${monitor.id}"]`)
    if (!video) return
    const current = players.get(monitor.id)
    if (current?.url === monitor.streamUrl && current.element === video) return
    destroyPlayer(monitor.id)
    playerErrors[monitor.id] = ''
    if (!flvjs.isSupported()) {
      playerErrors[monitor.id] = '当前浏览器不支持 FLV 直播画面。'
      return
    }
    const player = flvjs.createPlayer({ type: 'flv', isLive: true, url: monitor.streamUrl }, {
      enableStashBuffer: false,
      stashInitialSize: 128,
      autoCleanupSourceBuffer: true,
    })
    player.attachMediaElement(video)
    player.load()
    player.play().catch(() => {})
    player.on(flvjs.Events.ERROR, () => {
      playerErrors[monitor.id] = '画面连接中断，可点击刷新视频流重试。'
    })
    players.set(monitor.id, { player, url: monitor.streamUrl, element: video })
  })
}

onMounted(async () => {
  try {
    await getMonitorHealth()
  } catch (error) {
    errorMessage.value = error.message
  }
  await loadState()
  pollTimer = window.setInterval(() => loadState({ silent: true }), 1000)
})

onBeforeUnmount(() => {
  window.clearInterval(pollTimer)
  window.clearTimeout(noticeTimer)
  players.forEach((_value, id) => destroyPlayer(id))
})
</script>

<template>
  <main class="live-monitor-page">
    <section class="monitor-header">
      <div class="container monitor-header-inner">
        <div>
          <p class="eyebrow">LIVE OPERATIONS</p>
          <h1>直播间监控</h1>
          <p>实时查看直播画面和在线人数，统一管理告警、曲线与监控记录。</p>
        </div>
        <div class="service-state" :class="{ offline: !serviceOnline }">
          <Wifi :size="18" aria-hidden="true" />
          <span>{{ serviceOnline ? '本地监控服务在线' : '本地监控服务离线' }}</span>
          <strong>{{ activeCount }} 个运行中</strong>
        </div>
      </div>
    </section>

    <section class="container monitor-workbench">
      <nav class="monitor-tabs" aria-label="直播间监控功能">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          :class="{ active: activeTab === tab.id }"
          @click="activeTab = tab.id"
        >
          <component :is="tab.icon" :size="17" aria-hidden="true" />
          {{ tab.label }}
          <span v-if="tab.id === 'monitor' && activeCount">{{ activeCount }}</span>
        </button>
      </nav>

      <p v-if="errorMessage" class="monitor-error" role="alert">{{ errorMessage }}</p>

      <template v-if="activeTab === 'monitor'">
        <form class="monitor-start-bar" @submit.prevent="submitMonitor">
          <label for="douyin-room">抖音号或直播间网址</label>
          <div class="monitor-start-controls">
            <input
              id="douyin-room"
              v-model="douyinId"
              type="text"
              autocomplete="off"
              placeholder="输入抖音号，或粘贴 live.douyin.com 直播间网址"
            />
            <button class="monitor-primary" type="submit" :disabled="submitting">
              <RefreshCw v-if="submitting" class="spin" :size="17" aria-hidden="true" />
              <Plus v-else :size="18" aria-hidden="true" />
              {{ submitting ? '正在启动' : '开始监控' }}
            </button>
          </div>
        </form>

        <div v-if="loading" class="monitor-empty"><RefreshCw class="spin" :size="22" />正在读取监控状态</div>
        <div v-else-if="!monitors.length" class="monitor-empty">
          <Video :size="28" aria-hidden="true" />
          <strong>暂无运行中的直播间</strong>
          <span>输入抖音号或直播间网址开始监控。</span>
        </div>

        <div v-else class="monitor-list">
          <article v-for="monitor in monitors" :key="monitor.id" class="monitor-panel">
            <header class="monitor-panel-heading">
              <div class="monitor-identity">
                <span class="monitor-status-dot" :class="`is-${monitor.status}`"></span>
                <div>
                  <h2>{{ monitor.roomTitle || monitor.douyinId }}</h2>
                  <p>@{{ monitor.douyinId }} · {{ statusLabel(monitor.status) }}</p>
                </div>
              </div>
              <div class="monitor-heading-actions">
                <a
                  v-if="monitor.douyinId"
                  class="icon-command"
                  :href="`https://www.douyin.com/search/${encodeURIComponent(monitor.douyinId)}`"
                  target="_blank"
                  rel="noreferrer"
                  title="在抖音中打开"
                ><ExternalLink :size="17" aria-hidden="true" /></a>
                <button
                  class="icon-command"
                  type="button"
                  title="刷新视频流"
                  :disabled="actionId === monitor.id"
                  @click="runAction(monitor.id, refreshMonitorStream, '视频流已刷新')"
                ><RefreshCw :size="17" aria-hidden="true" /></button>
                <button
                  class="monitor-stop"
                  type="button"
                  :disabled="actionId === monitor.id"
                  @click="runAction(monitor.id, stopMonitor, '监控已停止')"
                ><Square :size="14" fill="currentColor" aria-hidden="true" />停止</button>
              </div>
            </header>

            <div class="monitor-live-grid">
              <div class="monitor-video-frame">
                <video
                  v-if="monitor.videoReady"
                  :data-monitor-video="monitor.id"
                  controls
                  autoplay
                  muted
                  playsinline
                ></video>
                <div v-else class="video-placeholder">
                  <RefreshCw v-if="['starting', 'resolving', 'connecting'].includes(monitor.status)" class="spin" :size="24" />
                  <Video v-else :size="26" />
                  <span>{{ monitor.statusMessage || '正在等待直播视频流' }}</span>
                </div>
                <p v-if="playerErrors[monitor.id]" class="video-error">{{ playerErrors[monitor.id] }}</p>
              </div>

              <div class="monitor-insights">
                <div class="audience-summary">
                  <span><Eye :size="16" aria-hidden="true" />实时在线</span>
                  <strong>{{ formatCount(monitor.currentCount) }}</strong>
                  <small>人</small>
                </div>

                <div class="monitor-chart-block">
                  <div class="chart-heading">
                    <div><Activity :size="17" aria-hidden="true" /><strong>实时在线人数曲线</strong></div>
                    <div class="interval-control" aria-label="曲线时间间隔">
                      <button
                        v-for="interval in intervals"
                        :key="interval"
                        type="button"
                        :class="{ active: monitorIntervals[monitor.id] === interval }"
                        @click="monitorIntervals[monitor.id] = interval"
                      >{{ interval }}分钟</button>
                    </div>
                  </div>
                  <LiveAudienceChart
                    :points="monitor.points"
                    :alerts="monitor.alerts"
                    :started-at="monitor.startedAt"
                    :interval-minutes="monitorIntervals[monitor.id]"
                  />
                </div>

                <dl class="monitor-details">
                  <div><dt>监控时长</dt><dd>{{ formatDuration(monitor.startedAt) }}</dd></div>
                  <div><dt>曲线数据</dt><dd>{{ monitor.points.length }} 个</dd></div>
                  <div><dt>告警次数</dt><dd :class="{ warning: monitor.alerts.length }">{{ monitor.alerts.length }} 次</dd></div>
                  <div><dt>当前规则</dt><dd>{{ ruleLabel(monitor.config) }}</dd></div>
                </dl>
              </div>
            </div>
          </article>
        </div>
      </template>

      <template v-else-if="activeTab === 'config'">
        <div v-if="!monitors.length" class="monitor-empty">
          <Settings :size="28" aria-hidden="true" />
          <strong>暂无可配置的直播间</strong>
          <span>开始监控后，可为每个直播间单独设置飞书告警。</span>
        </div>
        <div v-else class="config-list">
          <form
            v-for="monitor in monitors"
            :key="monitor.id"
            class="config-panel"
            @change="configDirty[monitor.id] = true"
            @submit.prevent="saveConfig(monitor)"
          >
            <header>
              <div>
                <h2>{{ monitor.roomTitle || monitor.douyinId }}</h2>
                <p>@{{ monitor.douyinId }}</p>
              </div>
              <label class="switch-control">
                <input v-model="configDrafts[monitor.id].enabled" type="checkbox" />
                <span></span>
                启用飞书告警
              </label>
            </header>

            <div class="config-grid">
              <fieldset>
                <legend>触发条件</legend>
                <div class="mode-control">
                  <label><input v-model="configDrafts[monitor.id].mode" type="radio" value="greater" />超过阈值</label>
                  <label><input v-model="configDrafts[monitor.id].mode" type="radio" value="less" />低于阈值</label>
                  <label><input v-model="configDrafts[monitor.id].mode" type="radio" value="range" />进入区间</label>
                </div>
                <div v-if="configDrafts[monitor.id].mode === 'range'" class="number-pair">
                  <label>最小人数<input v-model.number="configDrafts[monitor.id].min" type="number" min="0" /></label>
                  <label>最大人数<input v-model.number="configDrafts[monitor.id].max" type="number" min="0" /></label>
                </div>
                <label v-else class="number-field">
                  人数阈值
                  <input v-model.number="configDrafts[monitor.id].threshold" type="number" min="0" />
                </label>
              </fieldset>

              <fieldset>
                <legend>发送设置</legend>
                <label class="form-field">飞书 Webhook<input v-model.trim="configDrafts[monitor.id].webhook" type="url" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." /></label>
                <label class="form-field">签名密钥<input v-model.trim="configDrafts[monitor.id].secret" type="password" autocomplete="new-password" placeholder="未启用签名时可留空" /></label>
                <div class="cooldown-row">
                  <label class="switch-control compact"><input v-model="configDrafts[monitor.id].cooldownEnabled" type="checkbox" /><span></span>启用冷却</label>
                  <label>冷却时间<input v-model.number="configDrafts[monitor.id].cooldownMinutes" type="number" min="1" />分钟</label>
                </div>
              </fieldset>
            </div>

            <footer>
              <span>{{ ruleLabel(configDrafts[monitor.id]) }}</span>
              <button class="monitor-primary" type="submit" :disabled="actionId === monitor.id">
                <Save :size="17" aria-hidden="true" />保存配置
              </button>
            </footer>
          </form>
        </div>
      </template>

      <template v-else>
        <div v-if="!logs.length" class="monitor-empty">
          <ChartNoAxesCombined :size="28" aria-hidden="true" />
          <strong>暂无监控日志</strong>
          <span>开始一次监控后，记录会显示在这里。</span>
        </div>
        <div v-else class="log-list">
          <article v-for="log in logs" :key="log.id" class="log-panel">
            <button class="log-summary" type="button" @click="toggleLog(log.id)">
              <span class="monitor-status-dot" :class="`is-${log.status}`"></span>
              <span class="log-name"><strong>{{ log.roomTitle || log.douyinId }}</strong><small>@{{ log.douyinId }}</small></span>
              <span><small>开始时间</small><strong>{{ formatDate(log.startedAt) }}</strong></span>
              <span><small>监控时长</small><strong>{{ formatDuration(log.startedAt, log.endedAt) }}</strong></span>
              <span><small>最高在线</small><strong>{{ formatCount(Math.max(0, ...log.points.map((point) => point.count))) }} 人</strong></span>
              <span class="log-status" :class="`is-${log.status}`">{{ statusLabel(log.status) }}</span>
              <ChevronDown :size="18" :class="{ rotated: expandedLogs.has(log.id) }" aria-hidden="true" />
            </button>

            <div v-if="expandedLogs.has(log.id)" class="log-detail">
              <div class="chart-heading">
                <div><Activity :size="17" aria-hidden="true" /><strong>在线人数曲线</strong></div>
                <div class="interval-control">
                  <button
                    v-for="interval in intervals"
                    :key="interval"
                    type="button"
                    :class="{ active: logIntervals[log.id] === interval }"
                    @click="logIntervals[log.id] = interval"
                  >{{ interval }}分钟</button>
                </div>
              </div>
              <LiveAudienceChart
                :points="log.points"
                :alerts="log.alerts"
                :started-at="log.startedAt"
                :ended-at="log.endedAt"
                :interval-minutes="logIntervals[log.id]"
              />
              <div class="log-actions">
                <span>{{ log.endReason || (log.endedAt ? '监控已结束' : '正在监控') }} · {{ log.points.length }} 个数据点 · {{ log.alerts.length }} 次告警</span>
                <div>
                  <a
                    class="monitor-secondary"
                    :class="{ disabled: !log.points.length }"
                    :href="log.points.length ? monitorLogExportUrl(log.id) : undefined"
                    :aria-disabled="!log.points.length"
                  ><Download :size="16" aria-hidden="true" />导出报告</a>
                  <button
                    class="icon-command danger"
                    type="button"
                    title="删除监控日志"
                    :disabled="!log.endedAt || actionId === log.id"
                    @click="removeLog(log)"
                  ><Trash2 :size="17" aria-hidden="true" /></button>
                </div>
              </div>
            </div>
          </article>
        </div>
      </template>
    </section>

    <transition name="notice">
      <div v-if="notice" class="monitor-notice" role="status">{{ notice }}</div>
    </transition>
  </main>
</template>

<style scoped>
.live-monitor-page { min-height: calc(100vh - 82px); background: #f6f1ee; }
.monitor-header { padding: 64px 0 46px; border-bottom: 1px solid var(--line); background: #f8f4f1; }
.monitor-header-inner { display: flex; align-items: flex-end; justify-content: space-between; gap: 40px; }
.monitor-header .eyebrow { margin-bottom: 14px; }
.monitor-header h1 { margin-bottom: 12px; font-family: var(--serif); font-size: 46px; font-weight: 400; letter-spacing: 0; }
.monitor-header p:last-child { margin: 0; color: var(--muted); line-height: 1.8; }
.service-state { display: grid; grid-template-columns: auto auto; align-items: center; gap: 3px 9px; min-width: 220px; padding: 16px 18px; border: 1px solid rgba(49, 112, 78, .28); background: #f1f6f2; color: #286b45; font-size: 12px; }
.service-state svg { grid-row: 1 / 3; }
.service-state strong { color: #5c6b60; font-size: 11px; font-weight: 500; }
.service-state.offline { border-color: rgba(154, 63, 55, .28); background: #faf0ee; color: #943e38; }
.monitor-workbench { padding-block: 34px 100px; }
.monitor-tabs { display: flex; gap: 4px; padding-bottom: 18px; border-bottom: 1px solid var(--line); }
.monitor-tabs button { display: inline-flex; min-height: 42px; align-items: center; gap: 8px; padding: 0 18px; border: 0; background: transparent; color: #736765; cursor: pointer; }
.monitor-tabs button.active { background: var(--wine); color: #fff; }
.monitor-tabs button span { min-width: 20px; padding: 2px 6px; background: rgba(255,255,255,.18); font-size: 10px; text-align: center; }
.monitor-error { margin: 18px 0 0; padding: 13px 16px; border-left: 3px solid #a2483e; background: #f8e9e6; color: #87372f; font-size: 13px; line-height: 1.6; }
.monitor-start-bar { margin: 26px 0; padding: 22px 24px; border: 1px solid var(--line); background: #fff; }
.monitor-start-bar > label { display: block; margin-bottom: 9px; color: #5f4a48; font-size: 12px; font-weight: 600; }
.monitor-start-controls { display: grid; grid-template-columns: 1fr auto; gap: 10px; }
.monitor-start-controls input, .config-panel input { width: 100%; min-width: 0; border: 1px solid rgba(63,39,39,.2); background: #fff; color: var(--ink); outline: 0; }
.monitor-start-controls input { min-height: 46px; padding: 0 14px; }
.monitor-start-controls input:focus, .config-panel input:focus { border-color: var(--wine); box-shadow: 0 0 0 2px rgba(90,38,42,.08); }
.monitor-primary, .monitor-secondary, .monitor-stop, .icon-command { display: inline-flex; align-items: center; justify-content: center; gap: 8px; border: 0; cursor: pointer; }
.monitor-primary { min-height: 46px; padding: 0 20px; background: var(--wine); color: #fff; }
.monitor-primary:disabled, .monitor-stop:disabled, .icon-command:disabled { cursor: not-allowed; opacity: .48; }
.monitor-secondary { min-height: 38px; padding: 0 14px; border: 1px solid rgba(90,38,42,.34); color: var(--wine); font-size: 12px; }
.monitor-secondary.disabled { pointer-events: none; opacity: .42; }
.monitor-stop { min-height: 36px; padding: 0 13px; background: #efe3e0; color: #8d342f; font-size: 12px; }
.icon-command { width: 36px; height: 36px; border: 1px solid var(--line); background: #fff; color: #635552; }
.icon-command.danger { color: #963a34; }
.monitor-empty { display: grid; min-height: 270px; place-items: center; align-content: center; gap: 10px; border: 1px dashed rgba(63,39,39,.22); color: #8b7e7b; font-size: 13px; text-align: center; }
.monitor-empty strong { color: #594b49; font-family: var(--serif); font-size: 21px; font-weight: 400; }
.monitor-list, .config-list, .log-list { display: grid; gap: 20px; }
.monitor-panel, .config-panel, .log-panel { border: 1px solid var(--line); background: #fff; }
.monitor-panel-heading { display: flex; min-height: 78px; align-items: center; justify-content: space-between; gap: 24px; padding: 16px 20px; border-bottom: 1px solid var(--line); }
.monitor-identity { display: flex; min-width: 0; align-items: center; gap: 12px; }
.monitor-identity h2, .config-panel h2 { overflow: hidden; margin: 0 0 4px; font-family: var(--serif); font-size: 21px; font-weight: 400; text-overflow: ellipsis; white-space: nowrap; }
.monitor-identity p, .config-panel header p { margin: 0; color: var(--muted); font-size: 11px; }
.monitor-status-dot { flex: 0 0 auto; width: 9px; height: 9px; border-radius: 50%; background: #a29794; }
.monitor-status-dot.is-monitoring { background: #2d8051; box-shadow: 0 0 0 4px rgba(45,128,81,.12); }
.monitor-status-dot.is-warning { background: #c27b28; box-shadow: 0 0 0 4px rgba(194,123,40,.13); }
.monitor-status-dot.is-error { background: #ad4138; box-shadow: 0 0 0 4px rgba(173,65,56,.12); }
.monitor-status-dot.is-starting, .monitor-status-dot.is-resolving, .monitor-status-dot.is-connecting { background: #9e7429; }
.monitor-heading-actions { display: flex; flex: 0 0 auto; gap: 8px; }
.monitor-live-grid { display: grid; grid-template-columns: minmax(280px, 300px) minmax(0, 1fr); align-items: start; background: #f4efec; }
.monitor-video-frame { position: relative; width: 100%; aspect-ratio: 9 / 16; overflow: hidden; background: #1d1919; }
.monitor-video-frame video { display: block; width: 100%; height: 100%; object-fit: contain; background: #171414; }
.video-placeholder { display: grid; height: 100%; place-items: center; align-content: center; gap: 12px; color: #bcb2b0; font-size: 12px; }
.video-error { position: absolute; right: 12px; bottom: 12px; left: 12px; margin: 0; padding: 9px 11px; background: rgba(84,25,23,.88); color: #fff; font-size: 11px; }
.monitor-insights { min-width: 0; padding: 22px 22px 0; }
.audience-summary { margin-bottom: 14px; }
.audience-summary > span { display: flex; align-items: center; gap: 7px; color: #766967; font-size: 12px; }
.audience-summary > strong { display: inline-block; margin-top: 8px; font-family: Georgia, serif; font-size: 42px; font-weight: 400; line-height: 1; }
.audience-summary > small { margin-left: 7px; color: var(--muted); }
.monitor-chart-block { margin-bottom: 14px; }
.log-detail { padding: 20px; border-top: 1px solid var(--line); }
.monitor-details { margin: 0; }
.monitor-details > div { display: grid; grid-template-columns: 74px 1fr; gap: 14px; padding: 9px 0; border-top: 1px solid rgba(63,39,39,.12); font-size: 11px; line-height: 1.5; }
.monitor-details dt { color: #8c7f7c; }
.monitor-details dd { margin: 0; color: #524442; text-align: right; }
.monitor-details dd.warning { color: #a45e20; font-weight: 600; }
.chart-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 13px; }
.chart-heading > div:first-child { display: flex; align-items: center; gap: 8px; color: #594845; font-size: 12px; }
.interval-control { display: flex; border: 1px solid var(--line); }
.interval-control button { min-height: 30px; padding: 0 10px; border: 0; border-right: 1px solid var(--line); background: #fff; color: #817471; font-size: 10px; cursor: pointer; }
.interval-control button:last-child { border-right: 0; }
.interval-control button.active { background: #6a3a3d; color: #fff; }
.config-panel { padding: 0 22px 20px; }
.config-panel > header { display: flex; min-height: 82px; align-items: center; justify-content: space-between; gap: 24px; border-bottom: 1px solid var(--line); }
.switch-control { display: inline-flex; align-items: center; gap: 9px; color: #5d4c49; font-size: 12px; cursor: pointer; }
.switch-control input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.switch-control span { position: relative; width: 38px; height: 21px; border-radius: 12px; background: #c9bfbd; transition: background .2s; }
.switch-control span::after { content: ''; position: absolute; top: 3px; left: 3px; width: 15px; height: 15px; border-radius: 50%; background: #fff; transition: transform .2s; }
.switch-control input:checked + span { background: #347957; }
.switch-control input:checked + span::after { transform: translateX(17px); }
.switch-control.compact { flex: 0 0 auto; }
.config-grid { display: grid; grid-template-columns: 1fr 1.25fr; gap: 28px; padding: 24px 0; }
.config-panel fieldset { min-width: 0; margin: 0; padding: 0; border: 0; }
.config-panel legend { margin-bottom: 17px; color: #5c4745; font-size: 12px; font-weight: 600; }
.mode-control { display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid var(--line); }
.mode-control label { position: relative; display: grid; min-height: 40px; place-items: center; border-right: 1px solid var(--line); color: #776a68; font-size: 11px; cursor: pointer; }
.mode-control label:last-child { border-right: 0; }
.mode-control input { position: absolute; opacity: 0; }
.mode-control label:has(input:checked) { background: #6a3a3d; color: #fff; }
.number-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.number-field, .number-pair label, .form-field { display: grid; gap: 8px; margin-top: 15px; color: #776a68; font-size: 11px; }
.config-panel input[type='number'], .config-panel input[type='url'], .config-panel input[type='password'] { min-height: 40px; padding: 0 11px; }
.form-field:first-of-type { margin-top: 0; }
.cooldown-row { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-top: 15px; }
.cooldown-row > label:last-child { display: grid; grid-template-columns: auto 76px auto; align-items: center; gap: 8px; color: #776a68; font-size: 11px; }
.config-panel > footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding-top: 18px; border-top: 1px solid var(--line); color: #786b68; font-size: 11px; }
.log-panel { overflow: hidden; }
.log-summary { display: grid; width: 100%; min-height: 78px; grid-template-columns: auto minmax(150px, 1.25fr) 1fr .8fr .75fr auto auto; align-items: center; gap: 20px; padding: 13px 18px; border: 0; background: #fff; color: var(--ink); text-align: left; cursor: pointer; }
.log-summary:hover { background: #fbf8f6; }
.log-summary > span { min-width: 0; }
.log-summary small, .log-name small { display: block; overflow: hidden; margin-bottom: 5px; color: #8a7e7b; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.log-summary strong { display: block; overflow: hidden; font-size: 11px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.log-name strong { margin-bottom: 5px; font-family: var(--serif); font-size: 17px; font-weight: 400; }
.log-status { padding: 6px 9px; border: 1px solid var(--line); color: #756966; font-size: 10px; white-space: nowrap; }
.log-status.is-monitoring { border-color: rgba(45,128,81,.28); color: #287047; }
.log-status.is-warning { border-color: rgba(194,123,40,.32); color: #9b5e20; }
.log-status.is-error { border-color: rgba(173,65,56,.3); color: #983b35; }
.log-summary svg { transition: transform .2s; }
.log-summary svg.rotated { transform: rotate(180deg); }
.log-detail { background: #faf7f5; }
.log-actions { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding-top: 16px; color: #827572; font-size: 11px; }
.log-actions > div { display: flex; gap: 8px; }
.monitor-notice { position: fixed; z-index: 20; right: 24px; bottom: 24px; padding: 13px 18px; background: #2f6948; color: #fff; box-shadow: 0 10px 30px rgba(38,28,28,.18); font-size: 12px; }
.notice-enter-active, .notice-leave-active { transition: opacity .2s, transform .2s; }
.notice-enter-from, .notice-leave-to { opacity: 0; transform: translateY(8px); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 900px) {
  .monitor-header-inner { align-items: flex-start; flex-direction: column; }
  .service-state { width: 100%; }
  .monitor-live-grid, .config-grid { grid-template-columns: 1fr; }
  .monitor-video-frame { width: min(100%, 360px); margin-inline: auto; }
  .log-summary { grid-template-columns: auto minmax(140px, 1fr) 1fr auto auto; }
  .log-summary > span:nth-of-type(3), .log-summary > span:nth-of-type(4) { display: none; }
}

@media (max-width: 640px) {
  .monitor-header { padding: 42px 0 32px; }
  .monitor-header h1 { font-size: 36px; }
  .monitor-workbench { padding-block: 22px 70px; }
  .monitor-tabs { overflow-x: auto; }
  .monitor-tabs button { flex: 0 0 auto; padding-inline: 13px; }
  .monitor-start-bar { padding: 17px; }
  .monitor-start-controls { grid-template-columns: 1fr; }
  .monitor-panel-heading, .config-panel > header, .config-panel > footer, .log-actions, .chart-heading { align-items: stretch; flex-direction: column; }
  .monitor-heading-actions { align-self: stretch; }
  .monitor-heading-actions .monitor-stop { flex: 1; }
  .monitor-live-grid { min-height: 0; }
  .monitor-video-frame { width: min(100%, 320px); }
  .monitor-insights { padding: 18px 14px 0; }
  .monitor-chart-block, .log-detail { padding: 14px; }
  .interval-control { overflow-x: auto; }
  .interval-control button { flex: 1 0 auto; padding-inline: 8px; }
  .config-panel { padding-inline: 16px; }
  .config-panel > header { padding-block: 18px; }
  .mode-control { grid-template-columns: 1fr; }
  .mode-control label { border-right: 0; border-bottom: 1px solid var(--line); }
  .mode-control label:last-child { border-bottom: 0; }
  .cooldown-row { align-items: stretch; flex-direction: column; }
  .log-summary { grid-template-columns: auto minmax(0, 1fr) auto auto; gap: 10px; }
  .log-summary > span:nth-of-type(2), .log-summary > span:nth-of-type(3), .log-summary > span:nth-of-type(4) { display: none; }
  .log-status { font-size: 9px; }
}
</style>
