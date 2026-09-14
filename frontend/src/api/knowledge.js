export async function knowledgeRequest(path, params = {}, signal) {
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value != null))
  const response = await fetch(`/api/knowledge/${path}${query.size ? `?${query}` : ''}`, {
    credentials: 'same-origin', headers: { Accept: 'application/json' }, signal,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.message || '暂时无法加载知识内容，请稍后重试。')
  return data
}

export function knowledgeDate(value) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'Asia/Shanghai' }).format(new Date(value))
}
