import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request, StaleRequestError } from '@/api/client'
import { useAuthStore } from './auth'
import { useDraftsStore } from './drafts'

function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }) }
const identity = (id = 'user-a') => ({ user: { id, username: id }, session: { expires_at: new Date(Date.now() + 28_800_000).toISOString() } })
const csrf = () => ({ csrf_token: 'csrf-new', expires_at: new Date(Date.now() + 1_800_000).toISOString() })
const loggedIn = (id = 'user-a') => ({ ...identity(id), csrf_token: 'csrf-login', csrf_expires_at: new Date(Date.now() + 1_800_000).toISOString() })

describe('auth store', () => {
  let auth: ReturnType<typeof useAuthStore>
  const posted = vi.fn()
  beforeEach(() => {
    posted.mockReset()
    vi.stubGlobal('BroadcastChannel', class { postMessage = posted; close() {}; onmessage = null })
    setActivePinia(createPinia())
    auth = useAuthStore()
  })
  afterEach(() => { auth.$dispose(); vi.unstubAllGlobals() })
  function authenticate() {
    auth.user = identity().user
    auth.status = 'authenticated'
    auth.csrfToken = 'csrf-existing'
    auth.csrfExpiresAt = new Date(Date.now() + 1_800_000).toISOString()
  }

  it('shares initialization and confirms identity before fetching CSRF', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json(identity())).mockResolvedValueOnce(json(csrf()))
    vi.stubGlobal('fetch', fetcher)
    await Promise.all([auth.confirmIdentity(), auth.confirmIdentity()])
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(fetcher.mock.calls.map((call) => call[0])).toEqual(['/api/v1/auth/me', '/api/v1/auth/csrf'])
    expect(auth.authenticated).toBe(true)
  })
  it.each([new TypeError('offline'), new ApiError('不可用', 503, 'AUTH_DEPENDENCY_UNAVAILABLE')])('does not treat dependency failure as anonymous', async (error) => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(error))
    await auth.confirmIdentity()
    expect(auth.status).toBe('unavailable')
    expect(auth.authenticated).toBe(false)
  })
  it('turns initial AUTH_REQUIRED into anonymous, not server failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ code: 'AUTH_REQUIRED', message: '请登录' }, 401)))
    await auth.confirmIdentity()
    expect(auth.status).toBe('anonymous')
  })
  it('keeps credentials as entered and does not store passwords or session tokens', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(csrf())).mockResolvedValueOnce(json(loggedIn())))
    await auth.login(' User_A ', ' long password with spaces ')
    const fetcher = vi.mocked(fetch)
    expect(JSON.parse((fetcher.mock.calls[1][1] as RequestInit).body as string)).toEqual({ username: ' User_A ', password: ' long password with spaces ' })
    expect(JSON.stringify(auth.$state)).not.toContain('long password')
    expect(posted).toHaveBeenCalledWith({ type: 'changed' })
    expect(Object.keys(posted.mock.calls[0][0])).toEqual(['type'])
  })
  it('login credential failures stay at the form boundary', async () => {
    auth.status = 'anonymous'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(csrf())).mockResolvedValueOnce(json({ code: 'INVALID_CREDENTIALS', message: '用户名或密码错误' }, 401)))
    await expect(auth.login('user', 'bad')).rejects.toMatchObject({ code: 'INVALID_CREDENTIALS' })
    expect(auth.status).toBe('anonymous')
    expect(auth.authEpoch).toBe(0)
  })
  it('takes drafts before invalidation and restores only the same account', async () => {
    authenticate()
    const drafts = useDraftsStore()
    auth.onPrivateReset((reason) => { if (reason === 'expired') drafts.saveChat(auth.user!.id, 'conversation-a', '未提交') })
    auth.invalidate()
    expect(auth.user).toBeNull()
    expect(auth.status).toBe('reauthRequired')
    expect(auth.suspendedUserId).toBe('user-a')
    expect(auth.authEpoch).toBe(1)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(csrf())).mockResolvedValueOnce(json(loggedIn())))
    await auth.login('user-a', 'a long password')
    expect(drafts.takeChat('user-a', 'conversation-a', true)).toBe('未提交')
  })
  it('discards suspended drafts if login identifies another account', async () => {
    authenticate()
    const drafts = useDraftsStore()
    drafts.saveChat('user-a', 'conversation-a', 'private')
    drafts.saveCreation('user-a', 'title', { type: 'doc' })
    auth.invalidate()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(csrf())).mockResolvedValueOnce(json(loggedIn('user-b'))))
    await auth.login('user-b', 'a long password')
    expect(drafts.chats).toEqual([])
    expect(drafts.creation).toBeNull()
  })
  it('clears private content immediately but does not claim logout when server fails', async () => {
    authenticate()
    const drafts = useDraftsStore()
    drafts.saveChat('user-a', 'c', 'private')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({ code: 'AUTH_DEPENDENCY_UNAVAILABLE', message: '不可用' }, 503)).mockResolvedValueOnce(new Response(null, { status: 204 })))
    const task = auth.logout()
    expect(auth.status).toBe('loggingOut')
    expect(auth.user).toBeNull()
    expect(drafts.chats).toEqual([])
    await task
    expect(auth.status).toBe('logoutUncertain')
    expect(auth.notice).toContain('服务端退出尚未确认')
    await auth.logout()
    expect(auth.status).toBe('anonymous')
    expect(auth.notice).toBe('已退出当前会话。')
  })
  it('refreshes expired CSRF once before writes without replaying a rejected mutation', async () => {
    authenticate()
    auth.csrfExpiresAt = new Date(Date.now() - 1000).toISOString()
    const fetcher = vi.fn().mockResolvedValueOnce(json(csrf())).mockResolvedValueOnce(json({ code: 'CSRF_INVALID', message: 'CSRF失效' }, 403))
    vi.stubGlobal('fetch', fetcher)
    await expect(request('/conversations', { method: 'POST', body: '{}' }, { private: true })).rejects.toMatchObject({ code: 'CSRF_INVALID' })
    expect(fetcher.mock.calls.map((call) => call[0])).toEqual(['/api/v1/auth/csrf', '/api/v1/conversations'])
    expect(auth.status).toBe('authenticated')
    expect(auth.csrfToken).toBeNull()
  })
  it('shares one CSRF refresh for concurrent writes', async () => {
    authenticate()
    auth.csrfExpiresAt = new Date(Date.now() - 1000).toISOString()
    const fetcher = vi.fn((url: string) => Promise.resolve(json(url.endsWith('/csrf') ? csrf() : { ok: true })))
    vi.stubGlobal('fetch', fetcher)
    await Promise.all([request('/one', { method: 'POST' }, { private: true }), request('/two', { method: 'POST' }, { private: true })])
    expect(fetcher.mock.calls.filter((call) => call[0].endsWith('/csrf'))).toHaveLength(1)
  })
  it('rejects late login results after a logout broadcast', async () => {
    auth.csrfToken = 'csrf-existing'; auth.csrfExpiresAt = new Date(Date.now() + 10000).toISOString()
    let resolve!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((done) => { resolve = done })))
    const task = auth.login('user-a', 'password')
    await Promise.resolve()
    await auth.receiveBroadcast({ type: 'logout' })
    resolve(json(loggedIn()))
    await expect(task).rejects.toBeInstanceOf(StaleRequestError)
    expect(auth.status).toBe('anonymous')
    expect(auth.user).toBeNull()
  })
  it('rechecks the server on changed broadcasts instead of trusting payload identities', async () => {
    authenticate()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(identity('user-b'))).mockResolvedValueOnce(json(csrf())))
    await auth.receiveBroadcast({ type: 'changed', user: { id: 'forged' } })
    expect(auth.user?.id).toBe('user-b')
    expect(auth.authEpoch).toBe(1)
    expect(auth.csrfToken).toBe('csrf-new')
  })
  it('retains login on invalid current password and rotates epoch on successful change', async () => {
    authenticate()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json({ code: 'INVALID_CURRENT_PASSWORD', message: '当前密码错误' }, 400)).mockResolvedValueOnce(json(loggedIn())))
    await expect(auth.changePassword('wrong', 'new password long')).rejects.toMatchObject({ code: 'INVALID_CURRENT_PASSWORD' })
    expect(auth.authenticated).toBe(true)
    expect(auth.authEpoch).toBe(0)
    await auth.changePassword('current', 'new password long')
    expect(auth.authenticated).toBe(true)
    expect(auth.authEpoch).toBe(1)
    expect(auth.csrfToken).toBe('csrf-login')
    expect(posted).toHaveBeenCalledWith({ type: 'changed' })
  })
  it('isolates an unexpected different identity discovered on focus confirmation', async () => {
    authenticate()
    const reset = vi.fn()
    auth.onPrivateReset(reset)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(identity('user-b'))).mockResolvedValueOnce(json(csrf())))
    await auth.confirmIdentity()
    expect(auth.user?.id).toBe('user-b')
    expect(auth.authEpoch).toBe(1)
    expect(reset).toHaveBeenCalledWith('changed')
  })
})
