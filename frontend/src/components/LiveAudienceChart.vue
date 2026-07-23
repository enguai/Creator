<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  points: { type: Array, default: () => [] },
  alerts: { type: Array, default: () => [] },
  startedAt: { type: Number, required: true },
  endedAt: { type: Number, default: null },
  intervalMinutes: { type: Number, default: 5 },
})

const width = 900
const height = 250
const margin = { left: 58, right: 18, top: 16, bottom: 42 }
const plotWidth = width - margin.left - margin.right
const plotHeight = height - margin.top - margin.bottom
const hoverPoint = ref(null)
const svgRef = ref(null)

const sampledPoints = computed(() => {
  const source = [...props.points]
    .filter((point) => Number.isFinite(point?.time) && Number.isFinite(point?.count))
    .sort((left, right) => left.time - right.time)
  if (!source.length) return []
  const interval = props.intervalMinutes * 60000
  const result = [{ time: props.startedAt, count: source[0].count }]
  let nextBoundary = props.startedAt + interval
  source.forEach((point) => {
    if (point.time < nextBoundary) return
    const boundary = props.startedAt + Math.floor((point.time - props.startedAt) / interval) * interval
    result.push({ time: boundary, count: point.count })
    nextBoundary = boundary + interval
  })
  if (props.endedAt && source.at(-1).time > result.at(-1).time) {
    result.push({ time: props.endedAt, count: source.at(-1).count })
  }
  return result
})

const chart = computed(() => {
  const points = sampledPoints.value
  if (!points.length) return null
  const interval = props.intervalMinutes * 60000
  const start = props.startedAt
  const dataEnd = Math.max(props.endedAt || points.at(-1).time, start + interval)
  const end = start + Math.max(1, Math.ceil((dataEnd - start) / interval)) * interval
  const rawMax = Math.max(...points.map((point) => point.count), 1)
  const roughStep = rawMax / 5
  const magnitude = 10 ** Math.floor(Math.log10(Math.max(roughStep, 1)))
  const normalized = roughStep / magnitude
  const multiplier = [1, 2, 2.5, 5, 10].find((item) => normalized <= item) || 10
  const step = multiplier * magnitude
  const maximum = Math.max(5, step * 5)
  const x = (time) => margin.left + ((time - start) / (end - start)) * plotWidth
  const y = (count) => margin.top + plotHeight - (count / maximum) * plotHeight
  const path = points.map((point, index) => `${index ? 'L' : 'M'} ${x(point.time).toFixed(2)} ${y(point.count).toFixed(2)}`).join(' ')
  const slotCount = Math.max(1, Math.round((end - start) / interval))
  const stride = Math.max(1, Math.ceil(slotCount / 6))
  const xTicks = []
  for (let slot = 0; slot <= slotCount; slot += stride) xTicks.push(start + slot * interval)
  if (xTicks.at(-1) !== end) xTicks.push(end)
  return {
    points,
    start,
    end,
    x,
    y,
    path,
    yTicks: Array.from({ length: 6 }, (_, index) => step * index),
    xTicks,
  }
})

const tooltipStyle = computed(() => {
  if (!chart.value || !hoverPoint.value) return {}
  const pointX = chart.value.x(hoverPoint.value.time)
  const pointY = chart.value.y(hoverPoint.value.count)
  const clampedX = Math.max(84, Math.min(width - 84, pointX))
  const showBelow = pointY < 64
  return {
    left: `${clampedX / width * 100}%`,
    top: `${(showBelow ? pointY + 10 : pointY) / height * 100}%`,
    transform: showBelow ? 'translate(-50%, 0)' : 'translate(-50%, -115%)',
  }
})

function formatTick(value) {
  const date = new Date(value)
  const start = new Date(props.startedAt)
  const clock = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  return date.toDateString() === start.toDateString() ? clock : `${date.getMonth() + 1}/${date.getDate()} ${clock}`
}

function formatFull(value) {
  const date = new Date(value)
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`
}

function updateHover(event) {
  if (!chart.value || !svgRef.value) return
  const rect = svgRef.value.getBoundingClientRect()
  const chartX = ((event.clientX - rect.left) / rect.width) * width
  const target = chart.value.start + ((chartX - margin.left) / plotWidth) * (chart.value.end - chart.value.start)
  hoverPoint.value = chart.value.points.reduce((nearest, point) => (
    Math.abs(point.time - target) < Math.abs(nearest.time - target) ? point : nearest
  ))
}
</script>

<template>
  <div class="audience-chart">
    <div v-if="!chart" class="chart-empty">等待首次在线人数记录</div>
    <template v-else>
      <svg ref="svgRef" :viewBox="`0 0 ${width} ${height}`" preserveAspectRatio="none" aria-label="实时在线人数曲线图">
        <line
          v-for="tick in chart.yTicks"
          :key="`y-${tick}`"
          :x1="margin.left"
          :x2="width - margin.right"
          :y1="chart.y(tick)"
          :y2="chart.y(tick)"
          class="grid-line"
        />
        <text
          v-for="tick in chart.yTicks"
          :key="`yt-${tick}`"
          :x="margin.left - 8"
          :y="chart.y(tick) + 3"
          text-anchor="end"
          class="axis-label"
        >{{ Math.round(tick).toLocaleString('zh-CN') }}</text>
        <template v-for="tick in chart.xTicks" :key="`x-${tick}`">
          <line :x1="chart.x(tick)" :x2="chart.x(tick)" :y1="margin.top" :y2="margin.top + plotHeight" class="grid-line vertical" />
          <text :x="chart.x(tick)" :y="height - 16" text-anchor="middle" class="axis-label">{{ formatTick(tick) }}</text>
        </template>
        <line
          v-for="alert in alerts.filter((item) => item.time >= chart.start && item.time <= chart.end)"
          :key="`alert-${alert.time}`"
          :x1="chart.x(alert.time)"
          :x2="chart.x(alert.time)"
          :y1="margin.top"
          :y2="margin.top + plotHeight"
          class="alert-line"
        />
        <path :d="chart.path" class="data-line" />
        <template v-if="hoverPoint">
          <line :x1="chart.x(hoverPoint.time)" :x2="chart.x(hoverPoint.time)" :y1="margin.top" :y2="margin.top + plotHeight" class="hover-line" />
          <circle :cx="chart.x(hoverPoint.time)" :cy="chart.y(hoverPoint.count)" r="4" class="hover-dot" />
        </template>
        <rect
          :x="margin.left"
          :y="margin.top"
          :width="plotWidth"
          :height="plotHeight"
          class="chart-hit"
          @mousemove="updateHover"
          @mouseleave="hoverPoint = null"
        />
      </svg>
      <div
        v-if="hoverPoint"
        class="chart-tooltip"
        :style="tooltipStyle"
      >
        <span>{{ formatFull(hoverPoint.time) }}</span>
        <strong>{{ hoverPoint.count.toLocaleString('zh-CN') }} 人</strong>
      </div>
    </template>
  </div>
</template>

<style scoped>
.audience-chart { position: relative; width: 100%; height: 250px; background: #fff; border: 1px solid rgba(63, 39, 39, .12); overflow: hidden; }
.audience-chart svg { display: block; width: 100%; height: 100%; }
.grid-line { stroke: #ece3df; stroke-width: 1; }
.grid-line.vertical { stroke: #f3ece9; }
.axis-label { fill: #837572; font-size: 9px; }
.data-line { fill: none; stroke: #5a262a; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }
.alert-line { stroke: #a66c2d; stroke-width: 1; stroke-dasharray: 4 4; }
.hover-line { stroke: #786b68; stroke-width: 1; stroke-dasharray: 3 3; }
.hover-dot { fill: #fff; stroke: #5a262a; stroke-width: 2; }
.chart-hit { fill: transparent; }
.chart-empty { height: 100%; display: grid; place-items: center; color: #8b7e7b; font-size: 13px; }
.chart-tooltip { position: absolute; min-width: 136px; padding: 8px 10px; color: #fff; background: rgba(45, 32, 32, .94); pointer-events: none; font-size: 11px; line-height: 1.5; }
.chart-tooltip span, .chart-tooltip strong { display: block; }
@media (max-width: 720px) { .audience-chart { height: 220px; } }
</style>
