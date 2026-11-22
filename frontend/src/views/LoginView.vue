<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError, StaleRequestError } from '@/api/client'

const auth = useAuthStore()
const username = ref('')
const password = ref('')
const pending = ref(false)
const error = ref('')
const csrfReady = ref(false)
const retryAt = ref(0)
const waiting = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let mounted = true
const canLogin = computed(() => ['anonymous', 'reauthRequired'].includes(auth.status))

async function prepare() {
  const epoch = auth.authEpoch
  error.value = ''
  try {
    await auth.ensureCsrf()
    if (mounted && epoch === auth.authEpoch) csrfReady.value = true
  } catch (err) {
    if (mounted && epoch === auth.authEpoch) error.value = err instanceof Error ? err.message : '无法准备登录，请重试'
  }
}
async function submit() {
  if (pending.value || waiting.value || !canLogin.value || !csrfReady.value) return
  const epoch = auth.authEpoch
  error.value = ''
  if (Array.from(password.value).length > 128) { error.value = '密码不能超过 128 个字符。'; return }
  pending.value = true
  try {
    await auth.login(username.value, password.value)
  } catch (err) {
    if (!mounted || epoch !== auth.authEpoch || err instanceof StaleRequestError) return
    error.value = err instanceof ApiError && err.code === 'INVALID_CREDENTIALS' ? '用户名或密码错误' : err instanceof Error ? err.message : '登录失败，请重试'
    if (err instanceof ApiError && err.status === 429) {
      const seconds = Number(err.retryAfter)
      retryAt.value = Date.now() + (Number.isFinite(seconds) && seconds > 0 ? seconds : 60) * 1000
      waiting.value = true
      timer = setTimeout(() => { waiting.value = false }, retryAt.value - Date.now())
    }
    if (err instanceof ApiError && err.code === 'CSRF_INVALID') csrfReady.value = false
  } finally {
    if (mounted && epoch === auth.authEpoch) { password.value = ''; pending.value = false }
  }
}
watch(() => [auth.status, auth.authEpoch], () => {
  password.value = ''
  pending.value = false
  csrfReady.value = false
  waiting.value = false
  if (timer) clearTimeout(timer)
  if (canLogin.value) void prepare()
}, { immediate: true })
onBeforeUnmount(() => { mounted = false; password.value = ''; if (timer) clearTimeout(timer) })
</script>

<template>
  <main class="grid min-h-screen place-items-center bg-ink-50 px-5 py-12">
    <section class="panel w-full max-w-md p-7 sm:p-9">
      <p class="text-xs font-semibold uppercase tracking-widest text-brand-600">CreatorMind</p>
      <h1 class="mt-3 text-2xl font-semibold text-ink-950">{{ auth.status === 'reauthRequired' ? '重新登录' : '登录创作工作台' }}</h1>
      <p class="mt-2 text-sm leading-6 text-ink-500">使用本机初始化的账号安全访问你的创作内容。</p>
      <p v-if="auth.notice" role="status" class="mt-5 rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-800">{{ auth.notice }}</p>
      <p v-if="error" role="alert" class="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{{ error }}</p>
      <form v-if="canLogin" class="mt-6 space-y-4" @submit.prevent="submit">
        <div>
          <label for="login-username" class="mb-2 block text-sm font-medium text-ink-800">用户名</label>
          <input id="login-username" v-model="username" type="text" autocomplete="username" required maxlength="128" autofocus class="w-full rounded-xl border border-ink-200 px-3 py-3" :disabled="pending" />
        </div>
        <div>
          <label for="login-password" class="mb-2 block text-sm font-medium text-ink-800">密码</label>
          <input id="login-password" v-model="password" type="password" autocomplete="current-password" required class="w-full rounded-xl border border-ink-200 px-3 py-3" :disabled="pending" />
        </div>
        <button type="submit" class="btn-primary w-full" :disabled="pending || waiting || !csrfReady">{{ pending ? '登录中…' : waiting ? '请等待后再试' : '登录' }}</button>
        <button v-if="!csrfReady" type="button" class="text-sm text-brand-600" @click="prepare">重新准备登录</button>
      </form>
      <button v-if="auth.status === 'logoutUncertain'" type="button" class="btn-primary mt-5 w-full" @click="auth.logout">重试退出</button>
      <p v-if="auth.status === 'loggingOut'" class="mt-5 text-sm text-ink-500">正在确认服务端退出…</p>
      <div class="mt-7 border-t border-ink-100 pt-5 text-xs leading-6 text-ink-500">
        <p>首次使用需由本机维护者 ruoxili 创建账号；已有账号请直接登录。</p>
        <p>忘记密码请在本机使用 <code>python -m app.cli.auth reset-password --username &lt;用户名&gt;</code>。</p>
        <p class="mt-2">未提交草稿仅存在当前页面内存；刷新、关页会丢失，主动退出会立即清除。</p>
      </div>
    </section>
  </main>
</template>
