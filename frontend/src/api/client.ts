export interface HealthResponse {
  status: 'ok'
  service: string
  version: string
  environment: string
}

export interface Source {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  source_url: string | null
  created_at: string
}

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { headers, ...rest } = init ?? {}
  const response = await fetch(`${BASE_URL}${path}`, {
    ...rest,
    headers: {
      Accept: 'application/json',
      ...headers,
    },
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    if (typeof body?.detail === 'string') {
      throw new ApiError(body.detail, response.status)
    }
    if (typeof body?.detail?.[0]?.msg === 'string') {
      throw new ApiError(body.detail[0].msg, response.status)
    }
    throw new ApiError(`请求失败（HTTP ${response.status}）`, response.status)
  }

  return (await response.json()) as T
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  listSources: (limit: number, offset: number) =>
    request<Source[]>(`/sources?limit=${limit}&offset=${offset}`),
  uploadSource: (file: File, sourceUrl: string) => {
    const body = new FormData()
    body.set('file', file)
    if (sourceUrl) body.set('source_url', sourceUrl)
    return request<Source>('/sources', { method: 'POST', body })
  },
}
