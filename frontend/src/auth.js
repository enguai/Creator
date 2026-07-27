import { readonly, ref } from 'vue'

import { getAuthSession, loginAccount, logoutAccount, registerAccount } from './api/auth'

const currentUser = ref(null)
const authReady = ref(false)
let sessionRequest = null

export async function loadAuthSession(force = false) {
  if (authReady.value && !force) return currentUser.value
  if (sessionRequest && !force) return sessionRequest

  sessionRequest = getAuthSession()
    .then((session) => {
      currentUser.value = session.authenticated ? session.user : null
      authReady.value = true
      return currentUser.value
    })
    .catch(() => {
      currentUser.value = null
      authReady.value = true
      return null
    })
    .finally(() => {
      sessionRequest = null
    })
  return sessionRequest
}

export async function signIn(payload) {
  const session = await loginAccount(payload)
  currentUser.value = session.user
  authReady.value = true
  return currentUser.value
}

export async function signUp(payload) {
  const session = await registerAccount(payload)
  currentUser.value = session.user
  authReady.value = true
  return currentUser.value
}

export async function signOut() {
  try {
    await logoutAccount()
  } finally {
    currentUser.value = null
    authReady.value = true
  }
}

export function useAuth() {
  return {
    currentUser: readonly(currentUser),
    authReady: readonly(authReady),
  }
}
