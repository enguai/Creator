const API_BASE = '/api/live-monitor'

async function requestJson(url, options) {
  let response
  try {
    response = await fetch(url, options)
  } catch {
    throw new Error('无法连接直播监控服务，请确认本地 Django 已启动。')
  }
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.message || `直播监控服务返回 HTTP ${response.status}。`)
  }
  return payload
}

export function getMonitorHealth() {
  return requestJson(`${API_BASE}/health/`)
}

export function getMonitorState() {
  return requestJson(`${API_BASE}/state/`)
}

export function startMonitor(douyinId) {
  return requestJson(`${API_BASE}/monitors/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ douyinId }),
  })
}

export function stopMonitor(id) {
  return requestJson(`${API_BASE}/monitors/${id}/stop/`, { method: 'POST' })
}

export function refreshMonitorStream(id) {
  return requestJson(`${API_BASE}/monitors/${id}/refresh-stream/`, { method: 'POST' })
}

export function saveMonitorConfig(id, config) {
  return requestJson(`${API_BASE}/monitors/${id}/config/`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
}

export function deleteMonitorLog(id) {
  return requestJson(`${API_BASE}/logs/${id}/`, { method: 'DELETE' })
}

export function monitorLogExportUrl(id) {
  return `${API_BASE}/logs/${id}/export/`
}
