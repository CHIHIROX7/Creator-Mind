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

export interface ConversationSummary {
  id: string
  conversation_id: string
  summary: string
  covered_message_id: string | null
  message_count: number
  created_at: string
  updated_at: string
}

export interface AgentMemory {
  id: string
  user_id: string
  conversation_id: string | null
  source_message_id: string | null
  memory_type: 'preference' | 'constraint' | 'fact'
  content: string
  keywords: string[]
  importance: number
  status: 'active' | 'deleted'
  access_count: number
  last_accessed_at: string | null
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface ConversationMemory {
  conversation_id: string
  summary: ConversationSummary | null
  short_term_messages: Message[]
  long_term_memories: AgentMemory[]
  context: string
}

function http<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, init, { private: true })
}

export const conversationsApi = {
  list: () => http<Conversation[]>('/conversations'),
  create: (title = '新对话') => http<Conversation>('/conversations', {
    method: 'POST',
    body: JSON.stringify({ title }),
  }),
  rename: (id: string, title: string) => http<Conversation>(`/conversations/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  }),
  remove: (id: string) => http<void>(`/conversations/${id}`, { method: 'DELETE' }),
  messages: (id: string) => http<Message[]>(`/conversations/${id}/messages`),
  send: (id: string, content: string) => http<Message>(`/conversations/${id}/messages`, {
    method: 'POST',
    body: JSON.stringify({ role: 'user', content }),
  }),
  memory: (id: string) => http<ConversationMemory>(`/conversations/${id}/memory`),
  clearMemory: (id: string) => http<void>(`/conversations/${id}/memory`, { method: 'DELETE' }),
  deleteLongTermMemory: (id: string, memoryId: string) => http<void>(
    `/conversations/${id}/memory/long-term/${memoryId}`,
    { method: 'DELETE' },
  ),
}