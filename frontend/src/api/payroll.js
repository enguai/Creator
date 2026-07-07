const API_BASE = '/api/payroll'

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

  if (response.status === 404) {
    message = '没有连接到薪资计算后端 API。请确认 Django 后端已启动，并且服务器已把 /api/ 代理到 Django。'
  } else if (response.status === 413) {
    message = '上传文件超过服务器限制。请压缩图片，或在 Nginx/Django 中提高上传大小限制。'
  } else if (response.status >= 500 && !serverMessage) {
    message = '薪资计算后端发生错误。请查看 Django 控制台日志。'
  } else if (rawText.trim().startsWith('<!doctype') || rawText.trim().startsWith('<html')) {
    message = `请求没有到达薪资计算 API，服务器返回了网页内容（HTTP ${response.status}）。请检查 /api/ 代理配置。`
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
    throw new Error('无法连接到薪资计算后端。请确认 Django 服务已启动，或线上 Nginx 已正确代理 /api/。')
  }

  const payload = await readResponse(response)

  if (!response.ok) {
    throw buildHttpError(response, payload)
  }

  return payload
}

export async function checkPayrollHealth() {
  return requestJson(`${API_BASE}/health/`)
}

export async function createPayrollJob(formData) {
  return requestJson(`${API_BASE}/jobs/`, {
    method: 'POST',
    body: formData,
  })
}

export async function getPayrollJob(jobId) {
  return requestJson(`${API_BASE}/jobs/${jobId}/`)
}
