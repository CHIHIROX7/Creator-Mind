import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref } from 'vue'
import { authApi, type AuthResponse, type AuthUser, type IdentityResponse } from '@/api/auth'
import { abortAuthRequests, ApiError, registerAuthProvider, StaleRequestError } from '@/api/client'
import { useDraftsStore } from './drafts'

export type AuthStatus = 'unknown' | 'authenticated' | 'anonymous' | 'reauthRequired' | 'unavailable' | 'loggingOut' | 'logoutUncertain'
export type ResetReason = 'expired' | 'changed' | 'logout'

export const useAuthStore = defineStore('auth', () => {
  const status = ref<AuthStatus>('unknown')
  const user = ref<AuthUser | null>(null)
  const expiresAt = ref<string | null>(null)
  const csrfToken = ref<string | null>(null)
  const csrfExpiresAt = ref<string | null>(null)
  const authEpoch = ref(0)
  const suspendedUserId = ref<string | null>(null)
  const notice = ref('')
  const drafts = useDraftsStore()
  const resets = new Set<(reason: ResetReason) => void>()
  const authenticated = computed(() => status.value === 'authenticated' && user.value !== null)
  let initialization: Promise<void> | null = null
  let csrfTask: Promise<string> | null = null
  const channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('creatormind-auth')

  function onPrivateReset(callback: (reason: ResetReason) => void) {
    resets.add(callback)
    return () => resets.delete(callback)
  }
  function reset(reason: ResetReason) {
    for (const callback of resets) callback(reason)
    if (reason === 'logout') { drafts.clear(); suspendedUserId.value = null }
    else if (user.value) suspendedUserId.value = user.value.id
    authEpoch.value++
    abortAuthRequests()
    initialization = null
    csrfTask = null
    user.value = null
    expiresAt.value = null
  }
  function clearCsrf() { csrfToken.value = null; csrfExpiresAt.value = null }
  function invalidate() {
    if (!authenticated.value) return
    reset('expired')
    clearCsrf()
    status.value = 'reauthRequired'
    notice.value = '登录已过期。未提交草稿仅在当前页面内保留，同一账号重新登录后可恢复；刷新将丢失。'
  }
  function applyIdentity(identity: IdentityResponse) {
    drafts.acceptUser(identity.user.id)
    user.value = identity.user
    expiresAt.value = identity.session.expires_at
    suspendedUserId.value = null
    status.value = 'authenticated'
  }
  async function ensureCsrf(): Promise<string> {
    if (csrfToken.value && csrfExpiresAt.value && Date.parse(csrfExpiresAt.value) > Date.now()) return csrfToken.value
    if (csrfTask) return csrfTask
    const epoch = authEpoch.value
    const task = authApi.csrf().then((result) => {
      if (epoch !== authEpoch.value) throw new StaleRequestError()
      csrfToken.value = result.csrf_token
      csrfExpiresAt.value = result.expires_at
      return result.csrf_token
    }).finally(() => { if (csrfTask === task) csrfTask = null })
    csrfTask = task
    return task
  }
  function confirmIdentity(): Promise<void> {
    if (initialization) return initialization
    let epoch = authEpoch.value
    const task = (async () => {
      try {
        const identity = await authApi.me()
        if (epoch !== authEpoch.value) return
        if (user.value && user.value.id !== identity.user.id) {
          reset('changed')
          epoch = authEpoch.value
        }
        clearCsrf()
        await ensureCsrf()
        if (epoch !== authEpoch.value) return
        applyIdentity(identity)
      } catch (error) {
        if (epoch !== authEpoch.value) return
        if (error instanceof ApiError && error.status === 401 && ['AUTH_REQUIRED', 'SESSION_INVALID'].includes(error.code)) {
          if (user.value) reset('expired')
          clearCsrf()
          status.value = suspendedUserId.value ? 'reauthRequired' : 'anonymous'
        } else {
          if (user.value) reset('changed')
          status.value = 'unavailable'
          notice.value = '身份服务暂时不可用。请重试，私有内容不会在身份未知时加载。'
        }
      }
    })().finally(() => { if (initialization === task) initialization = null })
    initialization = task
    return task
  }
  function applyAuth(result: AuthResponse) {
    reset('changed')
    applyIdentity(result)
    csrfToken.value = result.csrf_token
    csrfExpiresAt.value = result.csrf_expires_at
  }
  async function login(username: string, password: string) {
    const epoch = authEpoch.value
    try {
      const result = await authApi.login(username, password)
      if (epoch !== authEpoch.value) throw new StaleRequestError()
      applyAuth(result)
      notice.value = ''
      channel?.postMessage({ type: 'changed' })
    } catch (error) {
      if (epoch !== authEpoch.value) throw new StaleRequestError()
      if (error instanceof ApiError && error.code === 'ALREADY_AUTHENTICATED') {
        await confirmIdentity()
        if (authenticated.value) return
      }
      if (error instanceof ApiError && error.code === 'CSRF_INVALID') clearCsrf()
      throw error
    }
  }
  async function logout() {
    if (status.value === 'loggingOut') return
    reset('logout')
    status.value = 'loggingOut'
    notice.value = ''
    channel?.postMessage({ type: 'logout' })
    const epoch = authEpoch.value
    try {
      await authApi.logout()
      if (epoch !== authEpoch.value) return
      clearCsrf()
      status.value = 'anonymous'
      notice.value = '已退出当前会话。'
      channel?.postMessage({ type: 'logout' })
    } catch (error) {
      if (epoch !== authEpoch.value) return
      if (error instanceof ApiError && error.code === 'CSRF_INVALID') clearCsrf()
      status.value = 'logoutUncertain'
      notice.value = '本地内容已清除，服务端退出尚未确认。请重试退出；刷新可能恢复仍有效的登录。'
    }
  }
  async function changePassword(currentPassword: string, newPassword: string) {
    const epoch = authEpoch.value
    try {
      const result = await authApi.password(currentPassword, newPassword)
      if (epoch !== authEpoch.value) throw new StaleRequestError()
      applyAuth(result)
      notice.value = '密码已修改，其他登录已失效，当前浏览器保持登录。'
      channel?.postMessage({ type: 'changed' })
    } catch (error) {
      if (epoch !== authEpoch.value) throw new StaleRequestError()
      if (error instanceof ApiError && error.code === 'CSRF_INVALID') clearCsrf()
      throw error
    }
  }
  async function receiveBroadcast(data: unknown) {
    if (!data || typeof data !== 'object' || !('type' in data)) return
    if (data.type === 'logout') {
      reset('logout'); clearCsrf(); status.value = 'anonymous'
      notice.value = '另一个标签页已发起退出，本地内容已清除。'
    } else if (data.type === 'changed') {
      reset('changed'); clearCsrf(); status.value = 'unknown'
      await confirmIdentity()
    }
  }
  if (channel) channel.onmessage = (event: MessageEvent<unknown>) => { void receiveBroadcast(event.data) }
  const onFocus = () => {
    if (status.value === 'authenticated') void confirmIdentity()
  }
  if (typeof window !== 'undefined') window.addEventListener('focus', onFocus)
  onScopeDispose(() => {
    channel?.close()
    if (typeof window !== 'undefined') window.removeEventListener('focus', onFocus)
    resets.clear()
  })
  registerAuthProvider({ epoch: () => authEpoch.value, csrf: ensureCsrf, invalid: invalidate, csrfInvalid: clearCsrf, allowed: () => authenticated.value })
  return { status, user, expiresAt, csrfToken, csrfExpiresAt, authEpoch, suspendedUserId, notice, authenticated, onPrivateReset, invalidate, ensureCsrf, confirmIdentity, login, logout, changePassword, receiveBroadcast }
})
