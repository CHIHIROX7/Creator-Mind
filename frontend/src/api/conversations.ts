import { request } from './client'

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
}

function http<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, init, { private: true })
}

export const conversationsApi = {
  list: () => http<Conversation[]>('/conversations'),
  create: (title = '新对话') => http<Conversation>('/conversations', { method: 'POST', body: JSON.stringify({ title }) }),
  rename: (id: string, title: string) => http<Conversation>(`/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  remove: (id: string) => http<void>(`/conversations/${id}`, { method: 'DELETE' }),
  messages: (id: string) => http<Message[]>(`/conversations/${id}/messages`),
  send: (id: string, content: string) => http<Message>(`/conversations/${id}/messages`, { method: 'POST', body: JSON.stringify({ role: 'user', content }) }),
}
