import { createRouter, createWebHistory } from 'vue-router'

import AppLayout from '@/layouts/AppLayout.vue'
import { useAuthStore } from '@/stores/auth'
import { safeRedirect } from './redirect'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录' },
    },
    {
      path: '/',
      component: AppLayout,
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: '创作工作台' },
        },
        {
          path: 'library',
          name: 'library',
          component: () => import('@/views/LibraryView.vue'),
          meta: { title: '作品与素材库' },
        },
        {
          path: 'creation',
          name: 'creation',
          component: () => import('@/views/CreationView.vue'),
          meta: { title: '多 Agent 创作' },
        },
        {
          path: 'conversations',
          name: 'conversations',
          component: () => import('@/views/ConversationsView.vue'),
          meta: { title: '多对话与消息' },
        },
        {
          path: 'memory',
          name: 'memory',
          component: () => import('@/views/MemoryView.vue'),
          meta: { title: '个性化记忆' },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
          meta: { title: '系统设置' },
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (auth.status === 'unknown') await auth.confirmIdentity()
  if (to.meta.requiresAuth && !auth.authenticated && auth.status !== 'unavailable' && auth.status !== 'unknown') {
    return { name: 'login', query: { redirect: safeRedirect(to.fullPath, router) } }
  }
  if (to.name === 'login' && auth.authenticated) return safeRedirect(to.query.redirect, router)
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : 'CreatorMind'
  document.title = `${title} · CreatorMind`
})

export default router