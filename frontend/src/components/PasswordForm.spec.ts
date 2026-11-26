import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PasswordForm from './PasswordForm.vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api/client'

describe('password form', () => {
  let auth: ReturnType<typeof useAuthStore>
  let wrapper: VueWrapper
  beforeEach(() => {
    vi.stubGlobal('BroadcastChannel', undefined)
    setActivePinia(createPinia())
    auth = useAuthStore()
    auth.user = { id: 'a', username: 'user_a' }; auth.status = 'authenticated'
    wrapper = mount(PasswordForm)
  })
  afterEach(() => { wrapper.unmount(); auth.$dispose(); vi.unstubAllGlobals() })
  async function fill(password: string) {
    const inputs = wrapper.findAll('input[type="password"]')
    await inputs[0].setValue(' current password ')
    await inputs[1].setValue(password)
    await inputs[2].setValue(password)
  }
  it('validates 15–128 characters without trimming spaces', async () => {
    const change = vi.spyOn(auth, 'changePassword').mockResolvedValue(undefined)
    await fill('short')
    await wrapper.get('form').trigger('submit')
    expect(change).not.toHaveBeenCalled()
    await fill(' 1234567890123 ')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(change).toHaveBeenCalledWith(' current password ', ' 1234567890123 ')
    expect(wrapper.findAll('input[type="password"]').every((input) => (input.element as HTMLInputElement).value === '')).toBe(true)
  })
  it('counts non-BMP passwords as characters rather than UTF16 units', async () => {
    const change = vi.spyOn(auth, 'changePassword').mockResolvedValue(undefined)
    await fill('𝒜'.repeat(128))
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(change).toHaveBeenCalledTimes(1)
  })
  it('keeps incorrect current password as a form error without logging out', async () => {
    vi.spyOn(auth, 'changePassword').mockRejectedValue(new ApiError('当前密码错误', 400, 'INVALID_CURRENT_PASSWORD'))
    await fill('long enough password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('当前密码错误')
    expect(auth.authenticated).toBe(true)
  })
  it('drops late form errors and clears secrets after identity expiry', async () => {
    let reject!: (error: Error) => void
    vi.spyOn(auth, 'changePassword').mockImplementation(() => new Promise((_resolve, fail) => { reject = fail }))
    await fill('long enough password')
    await wrapper.get('form').trigger('submit')
    auth.invalidate()
    reject(new Error('迟到密码错误'))
    await flushPromises()
    expect(wrapper.text()).not.toContain('迟到密码错误')
    expect(wrapper.findAll('input[type="password"]').every((input) => (input.element as HTMLInputElement).value === '')).toBe(true)
  })
})
