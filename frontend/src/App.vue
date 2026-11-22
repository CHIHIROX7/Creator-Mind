<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'

import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { safeRedirect } from '@/router/redirect'

const appStore = useAppStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

watch(() => [auth.status, route.fullPath], () => {
  if (['anonymous', 'reauthRequired', 'loggingOut', 'logoutUncertain'].includes(auth.status) && route.meta.requiresAuth) {
    void router.replace({ name: 'login', query: { redirect: safeRedirect(route.fullPath, router) } })
  } else if (auth.authenticated && route.name === 'login') {
    void router.replace(safeRedirect(route.query.redirect, router))
  }
}, { immediate: true })

onMounted(() => {
  void appStore.fetchHealth()
})
</script>

<template>
  <main v-if="auth.status === 'unknown' || auth.status === 'unavailable'" class="grid min-h-screen place-items-center bg-ink-50 p-6">
    <section class="panel max-w-md p-8 text-center">
      <h1 class="text-xl font-semibold text-ink-950">{{ auth.status === 'unknown' ? '正在确认登录身份…' : '暂时无法确认身份' }}</h1>
      <p class="mt-3 text-sm leading-6 text-ink-500">{{ auth.status === 'unavailable' ? auth.notice : '身份确认前不会加载私有内容。' }}</p>
      <button v-if="auth.status === 'unavailable'" type="button" class="btn-primary mt-5" @click="auth.confirmIdentity">重新确认身份</button>
    </section>
  </main>
  <RouterView v-else-if="!route.meta.requiresAuth || auth.authenticated" :key="route.meta.requiresAuth ? auth.authEpoch : 'public'" />
</template>