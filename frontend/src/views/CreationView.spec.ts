import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CreationView from './CreationView.vue'
import { useAuthStore } from '@/stores/auth'
import { useDraftsStore } from '@/stores/drafts'

const content = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: '编辑正文' }] }] }

describe('creation draft authentication boundary', () => {
  let auth: ReturnType<typeof useAuthStore>
  let wrapper: VueWrapper | undefined
  beforeEach(() => {
    vi.stubGlobal('BroadcastChannel', undefined)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    setActivePinia(createPinia())
    auth = useAuthStore()
    auth.user = { id: 'user-a', username: 'user_a' }
    auth.status = 'authenticated'
  })
  afterEach(() => { wrapper?.unmount(); auth.$dispose(); vi.unstubAllGlobals() })
  it('recovers title and JSON only for the confirmed same identity', async () => {
    useDraftsStore().saveCreation('user-a', '我的标题', content)
    wrapper = mount(CreationView)
    await flushPromises()
    expect((wrapper.get('#article-title').element as HTMLInputElement).value).toBe('我的标题')
    expect(wrapper.text()).toContain('编辑正文')
    expect(useDraftsStore().creation).toBeNull()
  })
  it('snapshots before editor clears and prevents stale repeated reset from overwriting content', async () => {
    useDraftsStore().saveCreation('user-a', '我的标题', content)
    wrapper = mount(CreationView)
    await flushPromises()
    auth.invalidate()
    await flushPromises()
    expect(useDraftsStore().creation?.title).toBe('我的标题')
    expect(useDraftsStore().creation?.content.content?.[0].content?.[0].text).toBe('编辑正文')
    await auth.receiveBroadcast({ type: 'changed' })
    expect(useDraftsStore().creation?.title).toBe('我的标题')
  })
  it('explicit logout clears article instead of keeping it as an expired draft', async () => {
    wrapper = mount(CreationView)
    await flushPromises()
    await wrapper.get('#article-title').setValue('private title')
    await auth.receiveBroadcast({ type: 'logout' })
    expect(useDraftsStore().creation).toBeNull()
    expect((wrapper.get('#article-title').element as HTMLInputElement).value).toBe('')
  })
})
