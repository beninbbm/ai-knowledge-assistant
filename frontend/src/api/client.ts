// A small wrapper around fetch that adds the login token and turns errors into
// readable messages. All requests go to /api/*, which Vite forwards to FastAPI.

const TOKEN_KEY = 'auth_token'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let onUnauthorized: () => void = () => {}

/** Called when the server says our login is no longer valid (e.g. it expired). */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // Storage unavailable (e.g. private mode): the login just won't survive a reload.
  }
}

function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') {
    const known: Record<string, string> = {
      LOGIN_BAD_CREDENTIALS: 'Wrong email or password.',
      REGISTER_USER_ALREADY_EXISTS: 'An account with that email already exists.',
    }
    return known[detail] ?? detail
  }
  if (Array.isArray(detail)) return detail.map((d) => d.msg ?? String(d)).join('; ')
  if (detail && typeof detail === 'object') {
    const d = detail as Record<string, unknown>
    if (typeof d.message === 'string') return d.message
    if (typeof d.reason === 'string') return d.reason
    return JSON.stringify(detail)
  }
  return `Request failed (${status})`
}

/** Low-level request: returns the Response (used directly for streaming). */
export async function rawRequest(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const resp = await fetch(`/api${path}`, { ...init, headers })
  if (resp.status === 401 && token) onUnauthorized()
  if (!resp.ok) {
    const body = await resp.json().catch(() => null)
    throw new ApiError(resp.status, errorMessage(resp.status, body))
  }
  return resp
}

/** JSON request. Pass a plain object as `json` to send it as the body. */
export async function api<T>(
  path: string,
  options: { method?: string; json?: unknown; body?: BodyInit } = {},
): Promise<T> {
  const init: RequestInit = { method: options.method ?? 'GET' }
  if (options.json !== undefined) {
    init.body = JSON.stringify(options.json)
    init.headers = { 'Content-Type': 'application/json' }
  } else if (options.body !== undefined) {
    init.body = options.body
  }
  const resp = await rawRequest(path, init)
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}
