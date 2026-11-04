import type { AgentEvent, FileNode, McpServerStatus, SessionFull, SessionSummary, Settings } from './types'

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

export const api = {
  health: () => fetch('/api/health').then((r) => j<Settings>(r)),

  saveSettings: (api_key?: string, model?: string, patch?: { approval_mode?: string; docker_sandbox?: boolean }) =>
    fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key, model, ...patch }),
    }).then((r) => j<Settings>(r)),

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

  /** POST chat and stream SSE events through a fetch reader (proxy-safe, abortable). */
  streamChat: async function (
    sid: string,
    text: string,
    onEvent: (ev: AgentEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const res = await fetch(`/api/sessions/${sid}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
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
              onEvent(JSON.parse(t.slice(5)) as AgentEvent)
            } catch { /* skip malformed */ }
          }
        }
      }
    }
  },
}
