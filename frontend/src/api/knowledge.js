export async function knowledgeRequest(path, params = {}, signal) {
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value != null))
  const response = await fetch(`/api/knowledge/${path}${query.size ? `?${query}` : ''}`, {
    credentials: 'same-origin', headers: { Accept: 'application/json' }, signal,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.message || '暂时无法加载知识内容，请稍后重试。')
  return data
}

export async function knowledgePost(path, payload, signal) {
  let response
  try {
    response = await fetch(`/api/knowledge/${path}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
  } catch {
    throw new Error('无法连接到知识中心服务，请检查网站后端是否已启动。')
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.message || '知识问答任务提交失败，请稍后重试。')
  return data
}

export async function knowledgeUpload(path, formData, signal) {
  let response
  try {
    response = await fetch(`/api/knowledge/${path}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      body: formData,
      signal,
    })
  } catch {
    throw new Error('无法连接到知识中心服务，请检查网站后端是否已启动。')
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.message || '知识问答任务提交失败，请稍后重试。')
  return data
}

export function knowledgeDate(value) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'Asia/Shanghai' }).format(new Date(value))
}
