const API_BASE = '/api/payroll'

export async function createPayrollJob(formData) {
  const response = await fetch(`${API_BASE}/jobs/`, {
    method: 'POST',
    body: formData,
  })

  const payload = await response.json().catch(() => ({}))

  if (!response.ok) {
    const message = payload.message || payload.error_message || '薪资计算任务提交失败，请稍后重试。'
    throw new Error(message)
  }

  return payload
}

export async function getPayrollJob(jobId) {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/`)
  const payload = await response.json().catch(() => ({}))

  if (!response.ok) {
    const message = payload.message || payload.error_message || '薪资计算任务状态查询失败。'
    throw new Error(message)
  }

  return payload
}
