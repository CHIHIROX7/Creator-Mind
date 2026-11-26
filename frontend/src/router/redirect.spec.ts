import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import { safeRedirect } from './redirect'

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: {}, meta: { requiresAuth: true } },
  { path: '/creation', component: {}, meta: { requiresAuth: true } },
  { path: '/login', component: {} },
] })

describe('safe site redirect', () => {
  it('keeps resolved private routes with query and hash', () => {
    expect(safeRedirect('/creation?tab=draft#title', router)).toBe('/creation?tab=draft#title')
  })
  it.each(['https://evil.example', '//evil.example', '/%2fevil.example', '/\\evil.example', '/%5cevil.example', '/login', '/login?redirect=/login', '/LOGIN/', '/missing', '/creation%0a', 'creation', null, ['/creation']])('rejects unsafe redirect %s', (path) => {
    expect(safeRedirect(path, router)).toBe('/')
  })
})
