const API_BASE = '/api/forms'

async function readResponse(response) {
  const contentType = response.headers.get('content-type') || ''

  if (contentType.includes('application/json')) {
    return response.json().catch(() => ({}))
  }

  return {
    rawText: await response.text().catch(() => ''),
  }
}

function buildHttpError(response, payload) {
  const rawText = payload.rawText || ''
  const serverMessage = payload.message || payload.error_message || payload.detail

  let message = serverMessage || `请求失败，服务器返回 HTTP ${response.status}。`

  if (response.status === 404 && payload.error === 'task_not_found') {
    message = payload.message || '没有找到这个任务，请检查任务 ID 是否完整。'
  } else if (response.status === 404) {
    message = '没有连接到报销助手后端 API。请确认 Django 后端已启动，并且 /api/ 已正确代理。'
  } else if (response.status === 413) {
    message = '上传材料超过服务器限制。请减少文件数量、压缩图片，或提高上传大小限制。'
  } else if (response.status >= 500 && !serverMessage) {
    message = '报销助手后端发生错误。请查看 Django 控制台日志。'
  } else if (rawText.trim().startsWith('<!doctype') || rawText.trim().startsWith('<html')) {
    message = `请求没有到达报销助手 API，服务器返回了网页内容（HTTP ${response.status}）。请检查 /api/ 代理配置。`
  }

  const error = new Error(message)
  error.status = response.status
  error.payload = payload
  return error
}

async function requestJson(url, options) {
  let response

  try {
    response = await fetch(url, options)
  } catch (error) {
    throw new Error('无法连接到报销助手后端。请确认 Django 服务已启动。')
  }

  const payload = await readResponse(response)

  if (!response.ok) {
    throw buildHttpError(response, payload)
  }

  return payload
}

export async function checkFormAutomationHealth() {
  return requestJson(`${API_BASE}/health/`)
}

export async function createFormAutomationJob(formData) {
  return requestJson(`${API_BASE}/jobs/`, {
    method: 'POST',
    body: formData,
  })
}

export async function getFormAutomationJob(jobId) {
  return requestJson(`${API_BASE}/jobs/${jobId}/`)
}

export async function getWorkerTask(jobId) {
  return requestJson(`/api/tasks/${encodeURIComponent(jobId)}/`)
}
