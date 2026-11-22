import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useDraftsStore } from './drafts'

describe('memory-only drafts', () => {
  beforeEach(() => setActivePinia(createPinia()))
  it('keys chat text by both owner and conversation and requires access validation', () => {
    const drafts = useDraftsStore()
    drafts.saveChat('a', 'one', 'first')
    drafts.saveChat('a', 'two', 'second')
    drafts.saveChat('b', 'one', 'other owner')
    expect(drafts.takeChat('a', 'one', false)).toBeUndefined()
    expect(drafts.takeChat('a', 'two', true)).toBe('second')
    expect(drafts.takeChat('b', 'one', true)).toBe('other owner')
  })
  it('copies Tiptap JSON and title without keeping mutable editor references', () => {
    const drafts = useDraftsStore()
    const content = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'original' }] }] }
    drafts.saveCreation('a', 'article', content)
    content.content[0].content[0].text = 'changed'
    const restored = drafts.takeCreation('a')
    expect(restored?.title).toBe('article')
    expect(restored?.content.content?.[0].content?.[0].text).toBe('original')
    expect(drafts.takeCreation('a')).toBeNull()
  })
  it('clears different-owner drafts and drops all drafts on explicit logout', () => {
    const drafts = useDraftsStore()
    drafts.saveChat('a', 'one', 'private')
    drafts.saveCreation('a', 'private', { type: 'doc' })
    drafts.acceptUser('b')
    expect(drafts.chats).toEqual([])
    expect(drafts.creation).toBeNull()
    drafts.saveChat('b', 'one', 'new')
    drafts.clear()
    expect(drafts.chats).toEqual([])
  })
  it('does not restore drafts into a new page runtime', () => {
    useDraftsStore().saveChat('a', 'one', 'lost on refresh')
    setActivePinia(createPinia())
    expect(useDraftsStore().chatTarget('a')).toBeUndefined()
  })
})
