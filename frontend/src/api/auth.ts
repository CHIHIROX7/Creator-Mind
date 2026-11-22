import { request } from './client'

export interface AuthUser { id: string; username: string }
export interface IdentityResponse { user: AuthUser; session: { expires_at: string } }
export interface AuthResponse extends IdentityResponse { csrf_token: string; csrf_expires_at: string }
export interface CsrfResponse { csrf_token: string; expires_at: string }

const scoped = { scoped: true }
export const authApi = {
  csrf: () => request<CsrfResponse>('/auth/csrf', {}, scoped),
  me: () => request<IdentityResponse>('/auth/me', {}, scoped),
  login: (username: string, password: string) => request<AuthResponse>('/auth/login', {
    method: 'POST', body: JSON.stringify({ username, password }),
  }, { scoped: true, csrf: true }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }, { scoped: true, csrf: true }),
  password: (current_password: string, new_password: string) => request<AuthResponse>('/auth/password', {
    method: 'POST', body: JSON.stringify({ current_password, new_password }),
  }, { private: true }),
}
