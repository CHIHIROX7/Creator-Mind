import type { Router } from 'vue-router'

export function safeRedirect(value: unknown, router: Router): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || /[\\\u0000-\u0020\u007f]/.test(value)) return '/'
  try {
    const decoded = decodeURIComponent(value)
    if (decoded.startsWith('//') || /[\\\u0000-\u0020\u007f]/.test(decoded)) return '/'
    const resolved = router.resolve(value)
    if (!resolved.matched.length || !resolved.meta.requiresAuth || resolved.path.replace(/\/+$/, '').toLowerCase() === '/login') return '/'
    return resolved.fullPath
  } catch { return '/' }
}
