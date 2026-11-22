import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { JSONContent } from '@tiptap/vue-3'

interface ChatDraft { userId: string; conversationId: string; text: string }
interface CreationDraft { userId: string; title: string; content: JSONContent }

export const useDraftsStore = defineStore('drafts', () => {
  const chats = ref<ChatDraft[]>([])
  const creation = ref<CreationDraft | null>(null)

  function clear() { chats.value = []; creation.value = null }
  function acceptUser(userId: string) {
    chats.value = chats.value.filter((draft) => draft.userId === userId)
    if (creation.value?.userId !== userId) creation.value = null
  }
  function saveChat(userId: string, conversationId: string, text: string) {
    chats.value = chats.value.filter((draft) => draft.userId !== userId || draft.conversationId !== conversationId)
    if (text) chats.value.push({ userId, conversationId, text })
  }
  function chatTarget(userId: string) { return chats.value.find((draft) => draft.userId === userId)?.conversationId }
  function takeChat(userId: string, conversationId: string, accessible: boolean) {
    const draft = chats.value.find((item) => item.userId === userId && item.conversationId === conversationId)
    chats.value = chats.value.filter((item) => item !== draft)
    return accessible ? draft?.text : undefined
  }
  function saveCreation(userId: string, title: string, content: JSONContent) {
    creation.value = { userId, title, content: JSON.parse(JSON.stringify(content)) as JSONContent }
  }
  function takeCreation(userId: string) {
    const draft = creation.value
    creation.value = null
    return draft?.userId === userId ? draft : null
  }
  return { chats, creation, clear, acceptUser, saveChat, chatTarget, takeChat, saveCreation, takeCreation }
})
