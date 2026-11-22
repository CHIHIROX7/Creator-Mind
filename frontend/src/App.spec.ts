import { createPinia, setActivePinia } from 'pinia'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'
import PasswordForm from '@/components/PasswordForm.vue'
import { useAuthStore } from '@/stores/auth'

const privateMounted = vi.fn()
const privatePage = defineComponent({ setup() { privateMounted() }, template: '<div data-testid="private-payload">真实私有业务数据</div>' })

describe('application mount boundary', () => {
  afterEach(() => { vi.unstubAllGlobals(); privateMounted.mockClear() })
  it('does not mount private components for unknown or unavailable identity', async () => {
    vi.stubGlobal('BroadcastChannel', undefined)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: privatePage, meta: { requiresAuth: true } }] })
    await router.push('/')
    const wrapper = mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(privateMounted).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="private-payload"]').exists()).toBe(false)
    auth.status = 'unavailable'
    await flushPromises()
    expect(privateMounted).not.toHaveBeenCalled()
    auth.user = { id: 'a', username: 'a' }; auth.status = 'authenticated'
    await flushPromises()
    expect(privateMounted).toHaveBeenCalledTimes(1)
    auth.status = 'unknown'
    await flushPromises()
    expect(wrapper.find('[data-testid="private-payload"]').exists()).toBe(false)
    wrapper.unmount(); auth.$dispose()
  })
  it('remounts a clean usable password form after successful epoch rotation', async () => {
    vi.stubGlobal('BroadcastChannel', undefined)
    const expiresAt = new Date(Date.now() + 1_800_000).toISOString()
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(url.endsWith('/auth/password') ? {
      user: { id: 'a', username: 'user_a' }, session: { expires_at: expiresAt }, csrf_token: 'csrf-replaced', csrf_expires_at: expiresAt,
    } : { status: 'ok', service: 'test', version: 'test', environment: 'test' }), { status: 200 }))))
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = { id: 'a', username: 'user_a' }; auth.status = 'authenticated'
    auth.csrfToken = 'csrf-existing'; auth.csrfExpiresAt = expiresAt
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/settings', component: PasswordForm, meta: { requiresAuth: true } }] })
    await router.push('/settings')
    const wrapper = mount(App, { global: { plugins: [pinia, router] } })
    await flushPromises()
    const oldForm = wrapper.get('form').element
    const inputs = wrapper.findAll('input[type="password"]')
    await inputs[0].setValue(' current password ')
    await inputs[1].setValue(' long new password ')
    await inputs[2].setValue(' long new password ')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(auth.authEpoch).toBe(1)
    expect(auth.authenticated).toBe(true)
    expect(auth.csrfToken).toBe('csrf-replaced')
    expect(wrapper.get('form').element).not.toBe(oldForm)
    expect((wrapper.get('button[type="submit"]').element as HTMLButtonElement).disabled).toBe(false)
    expect(wrapper.findAll('input[type="password"]').every((input) => (input.element as HTMLInputElement).value === '')).toBe(true)
    expect(wrapper.text()).toContain('密码已修改')
    wrapper.unmount(); auth.$dispose()
  })
})
