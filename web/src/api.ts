import type {
  AgentEvent, BatchEvent, FileNode, McpServerStatus, ModelInfo,
  SessionFull, SessionSummary, Settings, UsageTotals,
} from './types'

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const b = await res.json()
      if (b?.detail) msg = b.detail
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

/** Shared SSE reader: POST JSON, parse `data:` frames, dispatch to onEvent. */
async function sseRequest<T>(url: string, body: unknown, onEvent: (ev: T) => void, signal: AbortSignal): Promise<void> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    let msg = `HTTP ${res.status}`
    try {
      const b = await res.json()
      if (b?.detail) msg = b.detail
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
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
        if (t.startsWith('data:')) {
          try {
            onEvent(JSON.parse(t.slice(5)) as T)
          } catch { /* skip malformed */ }
        }
      }
    }
  }
}

export const api = {
  health: () => fetch('/api/health').then((r) => j<Settings>(r)),

  saveSettings: (api_key?: string, model?: string, patch?: { approval_mode?: string; docker_sandbox?: boolean }) =>
    fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key, model, ...patch }),
    }).then((r) => j<Settings>(r)),

  models: () => fetch('/api/models').then((r) => j<{ models: ModelInfo[]; count: number }>(r)),

  usage: () => fetch('/api/usage').then((r) => j<UsageTotals>(r)),

  mcpStatus: () =>
    fetch('/api/mcp').then((r) => j<{ servers: McpServerStatus[] }>(r)).then((d) => d.servers),

  mcpAdd: (name: string, command: string, args: string[]) =>
    fetch('/api/mcp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, command, args }),
    }).then((r) => j<{ servers: McpServerStatus[] }>(r)).then((d) => d.servers),

  mcpRemove: (name: string) =>
    fetch(`/api/mcp/${encodeURIComponent(name)}`, { method: 'DELETE' })
      .then((r) => j<{ servers: McpServerStatus[] }>(r)).then((d) => d.servers),

  mcpRefresh: (name: string) =>
    fetch(`/api/mcp/${encodeURIComponent(name)}/refresh`, { method: 'POST' })
      .then((r) => j<{ servers: McpServerStatus[] }>(r)).then((d) => d.servers),

  listSessions: () =>
    fetch('/api/sessions').then((r) => j<{ sessions: SessionSummary[] }>(r)).then((d) => d.sessions),

  createSession: () =>
    fetch('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      .then((r) => j<{ session: SessionSummary }>(r))
      .then((d) => d.session),

  getSession: (sid: string) =>
    fetch(`/api/sessions/${sid}`).then((r) => j<{ session: SessionFull }>(r)).then((d) => d.session),

  deleteSession: (sid: string) => fetch(`/api/sessions/${sid}`, { method: 'DELETE' }),

  tree: (sid: string) =>
    fetch(`/api/workspace/tree?sid=${encodeURIComponent(sid)}`)
      .then((r) => j<{ tree: FileNode[] }>(r))
      .then((d) => d.tree),

  readFile: (sid: string, path: string) =>
    fetch(`/api/workspace/file?sid=${encodeURIComponent(sid)}&path=${encodeURIComponent(path)}`).then((r) =>
      j<{ path: string; binary: boolean; content: string }>(r),
    ),

  saveFile: (sid: string, path: string, content: string) =>
    fetch(`/api/workspace/file?sid=${encodeURIComponent(sid)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    }).then((r) => j<{ ok: boolean }>(r)),

  deleteFile: (sid: string, path: string) =>
    fetch(`/api/workspace/file?sid=${encodeURIComponent(sid)}&path=${encodeURIComponent(path)}`, {
      method: 'DELETE',
    }).then((r) => j<{ ok: boolean }>(r)),

  /** POST chat and stream SSE events (proxy-safe, abortable). */
  streamChat: (sid: string, text: string, onEvent: (ev: AgentEvent) => void, signal: AbortSignal) =>
    sseRequest<AgentEvent>(`/api/sessions/${sid}/chat`, { text }, onEvent, signal),

  /** Parallel sub-agents: one prompt per line/task. */
  batchStream: (prompts: string[], onEvent: (ev: BatchEvent) => void, signal: AbortSignal) =>
    sseRequest<BatchEvent>('/api/batch', { prompts }, onEvent, signal),

  resolveApproval: (aid: string, decision: 'approve' | 'approve_always' | 'deny') =>
    fetch(`/api/approvals/${encodeURIComponent(aid)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    }).then((r) => j<{ ok: boolean }>(r)),

  uploadFiles: (sid: string, files: File[]) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    return fetch(`/api/workspace/upload?sid=${encodeURIComponent(sid)}`, {
      method: 'POST',
      body: fd,
    }).then((r) => j<{ saved: string[]; skipped: string[] }>(r))
  },

  exportUrl: (sid: string) => `/api/workspace/export?sid=${encodeURIComponent(sid)}`,
}
