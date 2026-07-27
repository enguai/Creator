function csrfToken() {
  const token = document.cookie
    .split('; ')
    .find((item) => item.startsWith('csrftoken='))
    ?.split('=', 2)[1]
  return token ? decodeURIComponent(token) : ''
}

async function requestJson(url, options = {}) {
  const method = options.method || 'GET'
  const headers = { Accept: 'application/json', ...(options.headers || {}) }
  if (method !== 'GET') {
    headers['Content-Type'] = 'application/json'
    headers['X-CSRFToken'] = csrfToken()
  }

  let response
  try {
    response = await fetch(url, {
      credentials: 'same-origin',
      ...options,
      headers,
    })
  } catch {
    throw new Error('无法连接到账号服务，请检查网站后端是否已启动。')
  }

  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = new Error(payload.message || `账号服务返回 HTTP ${response.status}。`)
    error.status = response.status
    error.payload = payload
    throw error
  }
  return payload
}

function post(url, payload) {
  return requestJson(url, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getAuthSession() {
  return requestJson('/api/auth/session/')
}

export function loginAccount(payload) {
  return post('/api/auth/login/', payload)
}

export function logoutAccount() {
  return post('/api/auth/logout/', {})
}

export function registerAccount(payload) {
  return post('/api/auth/register/', payload)
}

export function recoverAccount(payload) {
  return post('/api/auth/recover-account/', payload)
}

export function requestPasswordReset(payload) {
  return post('/api/auth/password-reset/', payload)
}

export function confirmPasswordReset(payload) {
  return post('/api/auth/password-reset-confirm/', payload)
}
