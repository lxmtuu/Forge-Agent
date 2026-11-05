import type {
  AgentEvent, BatchEvent, ContextStats, DoctorReport, FileNode,
  KeyCheckResult, McpServerStatus, ModelInfo,
  SessionFull, SessionSummary, Settings, UsageTotals,
  AuditEntry, ConnectorPreset, SkillInfo,
} from './types'

let csrfToken = ''

export interface AuthUser {
  id: string
  email: string
  name: string
  role: 'admin' | 'member' | string
  enabled: boolean
  picture?: string
  password_set: boolean
  google_linked: boolean
}

export interface GoogleAuthConfig {
  configured: boolean
  client_id: string
  public_url: string
  client_secret_set: boolean
}

export interface AuthState {
  user: AuthUser | null
  csrf_token: string
  google_enabled: boolean
  registration_enabled: boolean
  needs_setup: boolean
}

/** One fetch boundary: cookies same-origin + CSRF on every mutation/SSE. */
async function req(url: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken)
  }
  const res = await globalThis.fetch(url, { ...init, headers, credentials: 'same-origin' })
  if (res.status === 401 && !['/api/auth/login', '/api/auth/register'].includes(url)) {
    window.dispatchEvent(new CustomEvent('forge:unauthorized'))
  }
  return res
}

async function authMe(): Promise<AuthState> {
  const data = await req('/api/auth/me').then((r) => j<AuthState>(r))
  csrfToken = data.csrf_token
  return data
}

async function login(email: string, password: string): Promise<AuthUser> {
  await authMe()  // refresh double-submit cookie + in-memory token, never localStorage
  const data = await req('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  }).then((r) => j<{ user: AuthUser; csrf_token: string }>(r))
  csrfToken = data.csrf_token
  return data.user
}

async function register(email: string, password: string, name: string): Promise<AuthUser> {
  await authMe()
  const data = await req('/api/auth/register', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, name }),
  }).then((r) => j<{ user: AuthUser; csrf_token: string }>(r))
  csrfToken = data.csrf_token
  return data.user
}

function redactErrorText(text: string): string {
  return text
    .replace(/sk-or-v1-[a-z0-9_-]+/gi, '<redacted>')
    .replace(/AIza[a-z0-9_-]+/gi, '<redacted>')
    .replace(/Bearer\s+[a-z0-9._~+/=-]+/gi, 'Bearer <redacted>')
}

/** Đọc error body một lần; giữ status + endpoint và không nuốt non-JSON/empty 501. */
async function responseError(res: Response): Promise<Error> {
  let path = ''
  try { path = new URL(res.url).pathname } catch { /* response từ test/proxy có thể không có URL */ }
  const prefix = `HTTP ${res.status}${path ? ` · ${path}` : ''}`
  let raw = ''
  try { raw = await res.text() } catch { /* body có thể đã bị proxy huỷ */ }
  if (!raw.trim()) {
    return new Error(`${prefix} — Server không trả nội dung lỗi. Kiểm tra terminal đang chạy Forge và thử lại.`)
  }
  let detail = ''
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown; error?: unknown; message?: unknown }
    const value = parsed.detail ?? parsed.error ?? parsed.message
    if (typeof value === 'string') detail = value
    else if (Array.isArray(value)) {
      // FastAPI 422: chỉ lấy location/message, tuyệt đối không echo field `input` (có thể là secret).
      detail = value.map((row) => {
        const item = row as { loc?: unknown[]; msg?: unknown }
        const loc = Array.isArray(item?.loc) ? item.loc.join('.') : 'request'
        return `${loc}: ${typeof item?.msg === 'string' ? item.msg : 'không hợp lệ'}`
      }).join('; ')
    } else if (value && typeof value === 'object') {
      const message = (value as { message?: unknown }).message
      detail = typeof message === 'string' ? message : 'Yêu cầu không hợp lệ'
    }
  } catch {
    detail = raw
  }
  detail = redactErrorText(detail).replace(/\s+/g, ' ').trim().slice(0, 1000)
  return new Error(detail ? `${prefix} — ${detail}` : `${prefix} — Server không trả nội dung lỗi.`)
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) throw await responseError(res)
  return res.json() as Promise<T>
}

/** Shared SSE reader: POST JSON, parse `data:` frames, dispatch to onEvent. */
async function sseRequest<T>(url: string, body: unknown, onEvent: (ev: T) => void, signal: AbortSignal): Promise<void> {
  const res = await req(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw await responseError(res)
  if (!res.body) throw new Error(`HTTP ${res.status} · ${url} — Response không có body SSE`)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let sawDone = false
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      for (const line of raw.split('\n')) {
        const t = line.trim()
        if (!t.startsWith('data:')) continue
        let parsed: T
        try {
          parsed = JSON.parse(t.slice(5)) as T
        } catch { continue }  // chỉ bỏ frame malformed; không nuốt exception của onEvent
        if ((parsed as { type?: unknown })?.type === 'done') sawDone = true
        onEvent(parsed)
      }
    }
  }
  if (!sawDone && !signal.aborted) {
    throw new Error(`SSE ${url} kết thúc trước event done — kết nối/server có thể đã ngắt giữa chừng. Kiểm tra terminal Forge rồi thử lại.`)
  }
}

export const api = {
  authMe,
  login,
  register,
  logout: async () => { await req('/api/auth/logout', { method: 'POST' }) },
  registrationConfig: () => req('/api/auth/registration/config').then((r) => j<{ enabled: boolean }>(r)),
  setRegistrationEnabled: (enabled: boolean) =>
    req('/api/auth/registration/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }) }).then((r) => j<{ enabled: boolean }>(r)),
  listUsers: () => req('/api/auth/users').then((r) => j<AuthUser[]>(r)),
  inviteUser: (email: string, password: string | undefined, name: string, role: string) =>
    req('/api/auth/users', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, name, role }) }).then((r) => j<AuthUser>(r)),
  setUserEnabled: (id: string, enabled: boolean) =>
    req(`/api/auth/users/${encodeURIComponent(id)}`, { method: 'PATCH',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) })
      .then((r) => j<AuthUser>(r)),
  googleConfig: () => req('/api/auth/google/config').then((r) => j<GoogleAuthConfig>(r)),
  saveGoogleConfig: (client_id: string, client_secret: string, public_url: string) =>
    req('/api/auth/google/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id, client_secret, public_url }) }).then((r) => j<GoogleAuthConfig>(r)),
  health: () => req('/api/settings').then((r) => j<Settings>(r)),

  saveSettings: (api_key?: string, model?: string, patch?: { approval_mode?: string; docker_sandbox?: boolean; max_tokens?: number; web_search?: boolean; allow_commands?: string[]; deny_commands?: string[]; custom_base_url?: string; auto_commit?: boolean; reasoning_effort?: string; provider?: string }) =>
    req('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key, model, ...patch }),
    }).then((r) => j<Settings>(r)),

  keyCheck: (api_key?: string, provider = 'openrouter') =>
    req('/api/keycheck', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key, provider }),
    }).then((r) => j<KeyCheckResult>(r)),

  models: () => req('/api/models').then((r) => j<{ models: ModelInfo[]; count: number }>(r)),

  usage: () => req('/api/usage').then((r) => j<UsageTotals>(r)),

  mcpStatus: () =>
    req('/api/mcp').then((r) => j<{ servers: McpServerStatus[] }>(r)).then((d) => d.servers),

  mcpAdd: (name: string, command: string, args: string[]) =>
    req('/api/mcp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, command, args }),
    }).then((r) => j<{ servers: McpServerStatus[] }>(r)).then((d) => d.servers),

  mcpRemove: (name: string) =>
    req(`/api/mcp/${encodeURIComponent(name)}`, { method: 'DELETE' })
      .then((r) => j<{ servers: McpServerStatus[] }>(r)).then((d) => d.servers),

  mcpRefresh: (name: string) =>
    req(`/api/mcp/${encodeURIComponent(name)}/refresh`, { method: 'POST' })
      .then((r) => j<{ servers: McpServerStatus[] }>(r)).then((d) => d.servers),

  listSessions: () =>
    req('/api/sessions').then((r) => j<{ sessions: SessionSummary[] }>(r)).then((d) => d.sessions),

  createSession: (model?: string) =>
    req('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model }) })
      .then((r) => j<{ session: SessionSummary }>(r))
      .then((d) => d.session),

  getSession: (sid: string) =>
    req(`/api/sessions/${sid}`).then((r) => j<{ session: SessionFull }>(r)).then((d) => d.session),

  setSessionModel: (sid: string, model: string) =>
    req(`/api/sessions/${sid}/model`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model }),
    }).then((r) => j<{ ok: boolean; model: string; session: SessionSummary }>(r)),

  deleteSession: (sid: string) => req(`/api/sessions/${sid}`, { method: 'DELETE' }),

  tree: (sid: string) =>
    req(`/api/workspace/tree?sid=${encodeURIComponent(sid)}`)
      .then((r) => j<{ tree: FileNode[] }>(r))
      .then((d) => d.tree),

  readFile: (sid: string, path: string) =>
    req(`/api/workspace/file?sid=${encodeURIComponent(sid)}&path=${encodeURIComponent(path)}`).then((r) =>
      j<{ path: string; binary: boolean; content: string }>(r),
    ),

  saveFile: (sid: string, path: string, content: string) =>
    req(`/api/workspace/file?sid=${encodeURIComponent(sid)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    }).then((r) => j<{ ok: boolean }>(r)),

  deleteFile: (sid: string, path: string) =>
    req(`/api/workspace/file?sid=${encodeURIComponent(sid)}&path=${encodeURIComponent(path)}`, {
      method: 'DELETE',
    }).then((r) => j<{ ok: boolean }>(r)),

  /** POST chat and stream SSE events (proxy-safe, abortable). images = data URIs. */
  streamChat: (sid: string, text: string, mode: string, onEvent: (ev: AgentEvent) => void, signal: AbortSignal, images?: string[], rerun?: boolean, model?: string) =>
    sseRequest<AgentEvent>(`/api/sessions/${sid}/chat`, { text, mode, model, images: images ?? [], rerun: rerun ?? false }, onEvent, signal),

  rerun: (sid: string, index: number, text: string) =>
    req(`/api/sessions/${sid}/rerun`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index, text }),
    }).then((r) => j<{ ok: boolean; messages: number }>(r)),

  context: (sid: string) =>
    req(`/api/sessions/${sid}/context`).then((r) => j<ContextStats>(r)),

  doctor: () => req('/api/doctor').then((r) => j<DoctorReport>(r)),

  audit: (n = 120) =>
    req(`/api/audit?n=${n}`).then((r) => j<{ entries: AuditEntry[] }>(r)).then((d) => d.entries),

  connectorPresets: () =>
    req('/api/connectors/presets').then((r) => j<{ presets: ConnectorPreset[] }>(r)).then((d) => d.presets),
  oauthStart: (name: string, client_id?: string, client_secret?: string) =>
    req(`/api/connectors/${encodeURIComponent(name)}/oauth/start`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id, client_secret }),
    }).then((r) => j<{ ok: boolean }>(r)),
  oauthStatus: (name: string) =>
    req(`/api/connectors/${encodeURIComponent(name)}/oauth/status`).then((r) => j<{ status: string; detail: string; authorize_url?: string }>(r)),
  oauthDisconnect: (name: string) =>
    req(`/api/connectors/${encodeURIComponent(name)}/oauth`, { method: 'DELETE' }).then((r) => j<{ ok: boolean }>(r)),
  skills: (sid: string) =>
    req(`/api/skills?sid=${encodeURIComponent(sid)}`).then((r) => j<{ skills: SkillInfo[]; diags: string[] }>(r)),
  skillToggle: (sid: string, path: string, invocable: boolean) =>
    req(`/api/skills/toggle?sid=${encodeURIComponent(sid)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, invocable }),
    }).then((r) => j<{ ok: boolean; message: string }>(r)),
  skillTrust: (sid: string, name: string) =>
    req(`/api/skills/trust?sid=${encodeURIComponent(sid)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }).then((r) => j<{ ok: boolean; message: string }>(r)),
  connectorInstall: (id: string) =>
    req(`/api/connectors/install?id=${encodeURIComponent(id)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then((r) => j<{ ok: boolean; message: string }>(r)),
  connectorRemove: (id: string) =>
    req(`/api/connectors/${encodeURIComponent(id)}/installed`, { method: 'DELETE' }).then((r) => j<{ ok: boolean; message: string }>(r)),

  fork: (sid: string) =>
    req(`/api/sessions/${sid}/fork`, { method: 'POST' }).then((r) => j<{ session: { id: string; title: string } }>(r)),

  elicitation: (eid: string, action: string, content?: Record<string, unknown>) =>
    req(`/api/elicitation/${eid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, content }),
    }).then((r) => j<{ ok: boolean }>(r)),

  /** Parallel sub-agents: one prompt per line/task. */
  batchStream: (prompts: string[], onEvent: (ev: BatchEvent) => void, signal: AbortSignal, model?: string) =>
    sseRequest<BatchEvent>('/api/batch', { prompts, model }, onEvent, signal),

  /** ⚔ Battle: cùng 1 prompt chạy trên nhiều model song song. */
  battleStream: (prompt: string, models: string[], onEvent: (ev: BatchEvent) => void, signal: AbortSignal) =>
    sseRequest<BatchEvent>('/api/battle', { prompt, models }, onEvent, signal),

  /** Terminal tích hợp: chạy lệnh trong workspace. */
  exec: (sid: string, command: string) =>
    req(`/api/workspace/exec?sid=${encodeURIComponent(sid)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command }),
    }).then((r) => j<{ blocked: boolean; ok?: boolean; output: string }>(r)),

  /** Mở thư mục dự án thật làm workspace (cần FORGE_ALLOW_OPEN=1). */
  openWorkspace: (sid: string, path: string) =>
    req(`/api/workspace/open?sid=${encodeURIComponent(sid)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }).then((r) => j<{ ok: boolean; workspace: string }>(r)),

  undo: (sid: string) =>
    req(`/api/sessions/${sid}/undo`, { method: 'POST' })
      .then((r) => j<{ ok: boolean; message: string }>(r)),

  compact: (sid: string, instructions?: string) =>
    req(`/api/sessions/${sid}/compact`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instructions }),
    }).then((r) => j<{ ok: boolean; summary?: string; before?: number; after?: number; message?: string }>(r)),

  initAgents: (sid: string) =>
    req(`/api/sessions/${sid}/init`, { method: 'POST' })
      .then((r) => j<{ ok: boolean; path?: string; message?: string }>(r)),

  resolveApproval: (aid: string, decision: 'approve' | 'approve_always' | 'deny') =>
    req(`/api/approvals/${encodeURIComponent(aid)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    }).then((r) => j<{ ok: boolean }>(r)),

  uploadFiles: (sid: string, files: File[]) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    return req(`/api/workspace/upload?sid=${encodeURIComponent(sid)}`, {
      method: 'POST',
      body: fd,
    }).then((r) => j<{ saved: string[]; skipped: string[] }>(r))
  },

  exportUrl: (sid: string) => `/api/workspace/export?sid=${encodeURIComponent(sid)}`,
}
