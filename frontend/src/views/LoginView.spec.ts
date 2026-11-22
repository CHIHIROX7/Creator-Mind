import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LoginView from './LoginView.vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/client'

describe('login form identity boundary', () => {
  let auth: ReturnType<typeof useAuthStore>
  let wrapper: VueWrapper
  beforeEach(async () => {
    vi.stubGlobal('BroadcastChannel', undefined)
    setActivePinia(createPinia())
    auth = useAuthStore()
    auth.status = 'anonymous'
    vi.spyOn(auth, 'ensureCsrf').mockResolvedValue('csrf')
    wrapper = mount(LoginView)
    await flushPromises()
  })
  afterEach(() => { wrapper.unmount(); auth.$dispose(); vi.unstubAllGlobals() })
  async function fill() {
    await wrapper.get('#login-username').setValue(' User_A ')
    await wrapper.get('#login-password').setValue(' password with spaces ')
  }
  it('keeps invalid credentials on the form and clears password after failure', async () => {
    vi.spyOn(auth, 'login').mockRejectedValue(new ApiError('safe', 401, 'INVALID_CREDENTIALS'))
    await fill()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('用户名或密码错误')
    expect(auth.status).toBe('anonymous')
    expect((wrapper.get('#login-password').element as HTMLInputElement).value).toBe('')
  })
  it('resets old pending state on a logout broadcast and suppresses late errors', async () => {
    let reject!: (error: Error) => void
    const login = vi.spyOn(auth, 'login').mockImplementation(() => new Promise((_done, fail) => { reject = fail }))
    await fill()
    await wrapper.get('form').trigger('submit')
    expect(login).toHaveBeenCalledWith(' User_A ', ' password with spaces ')
    await auth.receiveBroadcast({ type: 'logout' })
    await flushPromises()
    expect((wrapper.get('button[type="submit"]').element as HTMLButtonElement).disabled).toBe(false)
    reject(new Error('迟到登录错误'))
    await flushPromises()
    expect(wrapper.text()).not.toContain('迟到登录错误')
    expect((wrapper.get('#login-password').element as HTMLInputElement).value).toBe('')
  })
  it('offers manual retry when anonymous CSRF preparation returns 503', async () => {
    wrapper.unmount()
    vi.mocked(auth.ensureCsrf).mockRejectedValueOnce(new ApiError('身份服务暂不可用', 503, 'AUTH_DEPENDENCY_UNAVAILABLE')).mockResolvedValue('csrf-fresh')
    wrapper = mount(LoginView)
    await flushPromises()
    expect(auth.status).toBe('anonymous')
    expect(wrapper.text()).toContain('身份服务暂不可用')
    expect(wrapper.text()).not.toContain('用户名或密码错误')
    expect((wrapper.get('button[type="submit"]').element as HTMLButtonElement).disabled).toBe(true)
    const retry = wrapper.findAll('button').find((button) => button.text() === '重新准备登录')!
    await retry.trigger('click')
    await flushPromises()
    expect((wrapper.get('button[type="submit"]').element as HTMLButtonElement).disabled).toBe(false)
  })
  it('reports login dependency failure without turning it into credential failure', async () => {
    vi.spyOn(auth, 'login').mockRejectedValue(new ApiError('登录服务暂不可用', 503, 'AUTH_DEPENDENCY_UNAVAILABLE'))
    await fill()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('登录服务暂不可用')
    expect(wrapper.text()).not.toContain('用户名或密码错误')
    expect(auth.status).toBe('anonymous')
  })
  it('does not automatically resubmit rejected CSRF mutations', async () => {
    const login = vi.spyOn(auth, 'login').mockRejectedValue(new ApiError('CSRF失效', 403, 'CSRF_INVALID'))
    await fill()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(login).toHaveBeenCalledTimes(1)
    expect((wrapper.get('button[type="submit"]').element as HTMLButtonElement).disabled).toBe(true)
    expect(wrapper.text()).toContain('重新准备登录')
  })
})
