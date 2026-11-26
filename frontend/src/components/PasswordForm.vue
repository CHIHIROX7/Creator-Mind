<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError, StaleRequestError } from '@/api/client'

const auth = useAuthStore()
const currentPassword = ref('')
const newPassword = ref('')
const confirmation = ref('')
const error = ref('')
const busy = ref(false)
const waiting = ref(false)
const epoch = auth.authEpoch
let alive = true
let timer: ReturnType<typeof setTimeout> | undefined
const isCurrent = () => alive && auth.authenticated && auth.authEpoch === epoch
function clearPasswords() { currentPassword.value = ''; newPassword.value = ''; confirmation.value = '' }
const unsubscribe = auth.onPrivateReset(clearPasswords)

async function submit() {
  if (!isCurrent() || busy.value || waiting.value) return
  error.value = ''
  if (Array.from(currentPassword.value).length > 128) { error.value = '当前密码不能超过 128 个字符。'; return }
  const length = Array.from(newPassword.value).length
  if (length < 15 || length > 128) { error.value = '新密码须为 15–128 个字符，不会裁剪空格。'; return }
  if (newPassword.value !== confirmation.value) { error.value = '两次新密码不一致。'; return }
  busy.value = true
  try {
    await auth.changePassword(currentPassword.value, newPassword.value)
  } catch (err) {
    if (!isCurrent() || err instanceof StaleRequestError) return
    error.value = err instanceof Error ? err.message : '修改密码失败'
    if (!(err instanceof ApiError)) error.value = '修改结果尚未确认，请使用新密码重新登录确认。不要自动重复提交。'
    if (err instanceof ApiError && err.status === 429) {
      const seconds = Number(err.retryAfter)
      waiting.value = true
      timer = setTimeout(() => { if (isCurrent()) waiting.value = false }, (Number.isFinite(seconds) && seconds > 0 ? seconds : 60) * 1000)
    }
  } finally {
    if (isCurrent()) { clearPasswords(); busy.value = false }
  }
}
onBeforeUnmount(() => { alive = false; unsubscribe(); clearPasswords(); if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="panel p-5 sm:p-6">
    <h3 class="panel-heading">账号与修改密码</h3>
    <p class="mt-2 text-sm text-ink-500">当前账号：<span class="font-medium text-ink-900">{{ auth.user?.username }}</span></p>
    <p v-if="auth.notice" role="status" class="mt-4 text-sm text-emerald-700">{{ auth.notice }}</p>
    <p v-if="error" role="alert" class="mt-4 text-sm text-red-700">{{ error }}</p>
    <form class="mt-5 grid max-w-xl gap-4" @submit.prevent="submit">
      <input :value="auth.user?.username" autocomplete="username" class="sr-only" tabindex="-1" readonly aria-label="用户名" />
      <label class="grid gap-2 text-sm text-ink-800">当前密码
        <input v-model="currentPassword" type="password" autocomplete="current-password" required :disabled="busy" class="rounded-xl border border-ink-200 px-3 py-3" />
      </label>
      <label class="grid gap-2 text-sm text-ink-800">新密码
        <input v-model="newPassword" type="password" autocomplete="new-password" required :disabled="busy" class="rounded-xl border border-ink-200 px-3 py-3" />
      </label>
      <label class="grid gap-2 text-sm text-ink-800">确认新密码
        <input v-model="confirmation" type="password" autocomplete="new-password" required :disabled="busy" class="rounded-xl border border-ink-200 px-3 py-3" />
      </label>
      <p class="text-xs leading-6 text-ink-500">新密码为 15–128 个字符，允许粘贴，空格不会裁剪。修改成功会使其他登录失效，当前浏览器保持登录。</p>
      <button type="submit" class="btn-primary w-fit" :disabled="busy || waiting">{{ busy ? '正在修改…' : waiting ? '请等待后再试' : '修改密码' }}</button>
    </form>
  </section>
</template>
