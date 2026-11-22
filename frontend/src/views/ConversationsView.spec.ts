import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ConversationsView from './ConversationsView.vue'
import { useAuthStore } from '@/stores/auth'
import { useDraftsStore } from '@/stores/drafts'
import { conversationsApi } from '@/api/conversations'

vi.mock('@/api/conversations', () => ({ conversationsApi: { list: vi.fn(), messages: vi.fn(), create: vi.fn(), rename: vi.fn(), remove: vi.fn(), send: vi.fn() } }))
const conversation = { id: 'one', title: '会话', created_at: '2026-01-01', updated_at: '2026-01-01' }

describe('conversation identity boundary', () => {
  let auth: ReturnType<typeof useAuthStore>
  let wrapper: VueWrapper | undefined
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('BroadcastChannel', undefined)
    setActivePinia(createPinia())
    auth = useAuthStore()
    auth.user = { id: 'user-a', username: 'user_a' }
    auth.status = 'authenticated'
    vi.mocked(conversationsApi.list).mockResolvedValue([conversation])
    vi.mocked(conversationsApi.messages).mockResolvedValue([])
  })
  afterEach(() => { wrapper?.unmount(); auth.$dispose(); vi.unstubAllGlobals() })

  it('snapshots unsent input before expiry and clears private data immediately', async () => {
    wrapper = mount(ConversationsView)
    await flushPromises()
    await wrapper.get('textarea').setValue('尚未发送')
    auth.invalidate()
    await flushPromises()
    expect(useDraftsStore().chats).toEqual([{ userId: 'user-a', conversationId: 'one', text: '尚未发送' }])
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('会话（1）')
  })
  it('restores text only after fresh list and message access verification', async () => {
    const drafts = useDraftsStore()
    drafts.saveChat('user-a', 'one', '恢复输入')
    let resolve!: (messages: []) => void
    vi.mocked(conversationsApi.messages).mockImplementation(() => new Promise<[]>((done) => { resolve = done }))
    wrapper = mount(ConversationsView)
    await flushPromises()
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
    resolve([])
    await flushPromises()
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('恢复输入')
    expect(wrapper.text()).toContain('已恢复')
  })
  it('preserves a suspended draft if identity expires again during resource validation', async () => {
    const drafts = useDraftsStore()
    drafts.saveChat('user-a', 'one', '尚未恢复的输入')
    let resolve!: (messages: []) => void
    vi.mocked(conversationsApi.messages).mockImplementation(() => new Promise<[]>((done) => { resolve = done }))
    wrapper = mount(ConversationsView)
    await flushPromises()
    auth.invalidate()
    resolve([])
    await flushPromises()
    expect(drafts.takeChat('user-a', 'one', true)).toBe('尚未恢复的输入')
    expect(wrapper.find('textarea').exists()).toBe(false)
  })
  it('drops a draft if the target is no longer accessible', async () => {
    const drafts = useDraftsStore()
    drafts.saveChat('user-a', 'deleted', 'private')
    wrapper = mount(ConversationsView)
    await flushPromises()
    expect(drafts.chats).toEqual([])
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
  })
  it.each(['success', 'error'])('ignores late %s and finally after identity expiry', async (outcome) => {
    let resolve!: (value: typeof conversation) => void
    let reject!: (reason: Error) => void
    vi.mocked(conversationsApi.create).mockImplementation(() => new Promise((done, fail) => { resolve = done; reject = fail }))
    wrapper = mount(ConversationsView)
    await flushPromises()
    await wrapper.get('button').trigger('click')
    auth.invalidate()
    await flushPromises()
    if (outcome === 'success') resolve({ ...conversation, id: 'late', title: '迟到私有内容' })
    else reject(new Error('迟到错误'))
    await flushPromises()
    expect(wrapper.text()).not.toContain('迟到')
    expect(wrapper.find('textarea').exists()).toBe(false)
  })
  it('does not save expired drafts on a normal route unmount', async () => {
    wrapper = mount(ConversationsView)
    await flushPromises()
    await wrapper.get('textarea').setValue('normal route draft')
    wrapper.unmount(); wrapper = undefined
    expect(useDraftsStore().chats).toEqual([])
  })
})
