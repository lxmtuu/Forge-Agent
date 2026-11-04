import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { uid } from './types'
import type { AgentEvent, FileNode, Item, SessionSummary, Settings } from './types'
import { Sidebar } from './components/Sidebar'
import { FilesPane } from './components/FilesPane'
import { SettingsModal } from './components/SettingsModal'
import { ToolCard } from './components/ToolCard'
import { Markdown } from './md'

/** Rebuild display timeline from persisted OpenAI-format messages. */
function buildTimeline(messages: { role: string; content: string | null; tool_calls?: { id: string; function: { name: string } }[]; tool_call_id?: string }[]): Item[] {
  const items: Item[] = []
  const pendingTools = new Map<string, Item & { kind: 'tool' }>()
  for (const m of messages) {
    if (m.role === 'user') {
      items.push({ kind: 'user', id: uid(), text: m.content ?? '' })
    } else if (m.role === 'assistant') {
      if (m.content) items.push({ kind: 'assistant', id: uid(), text: m.content, streaming: false })
      for (const tc of m.tool_calls ?? []) {
        const it: Item & { kind: 'tool' } = {
          kind: 'tool', id: uid(), callId: tc.id, name: tc.function.name,
          args: {}, output: null, ok: null,
        }
        items.push(it)
        pendingTools.set(tc.id, it)
      }
    } else if (m.role === 'tool') {
      const it = pendingTools.get(m.tool_call_id ?? '')
      if (it) {
        it.output = m.content ?? ''
        it.ok = !(m.content ?? '').startsWith('Error')
      }
    }
  }
  return items
}

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [sid, setSid] = useState<string | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [tree, setTree] = useState<FileNode[]>([])
  const [fileSel, setFileSel] = useState<string | null>(null)
  const [fileContent, setFileContent] = useState<string | null>(null)
  const [fileDirty, setFileDirty] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [errorBanner, setErrorBanner] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const itemsRef = useRef<Item[]>([])
  itemsRef.current = items

  const refreshSessions = useCallback(() => {
    api.listSessions().then(setSessions).catch(() => {})
  }, [])

  const loadSession = useCallback(async (id: string) => {
    try {
      const s = await api.getSession(id)
      setItems(buildTimeline(s.session.messages))
    } catch (e) { setErrorBanner(String(e)) }
  }, [])

  const refreshTree = useCallback(async (id: string) => {
    try { setTree(await api.tree(id)) } catch { /* ignore */ }
  }, [])

  // initial load
  useEffect(() => {
    api.health().then((s) => { setSettings(s); if (s.demo) setSettingsOpen(true) }).catch(() => {})
    refreshSessions()
    api.listSessions().then(async (list) => {
      if (list.length > 0) { setSid(list[0].id); await loadSession(list[0].id); refreshTree(list[0].id) }
      else {
        const s = await api.createSession()
        setSid(s.id); refreshSessions()
      }
    }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // autoscroll while streaming
  useEffect(() => {
    const el = chatScrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items])

  // ------------------------------------------------------------------ send
  async function send() {
    const text = input.trim()
    if (!text || !sid || streaming) return
    setInput('')
    setErrorBanner(null)
    setItems((prev) => [...prev, { kind: 'user', id: uid(), text }])
    setStreaming(true)
    const ac = new AbortController()
    abortRef.current = ac

    const mutate = (fn: (prev: Item[]) => Item[]) => setItems((prev) => fn(prev))

    try {
      await api.streamChat(sid, text, (ev: AgentEvent) => {
        switch (ev.type) {
          case 'reasoning_delta':
            mutate((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.kind === 'reasoning' && last.streaming) {
                return [...prev.slice(0, -1), { ...last, text: last.text + ev.text }]
              }
              return [...prev, { kind: 'reasoning', id: uid(), text: ev.text, streaming: true }]
            })
            break
          case 'assistant_delta':
            mutate((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.kind === 'assistant' && last.streaming) {
                return [...prev.slice(0, -1), { ...last, text: last.text + ev.text }]
              }
              return [...prev, { kind: 'assistant', id: uid(), text: ev.text, streaming: true }]
            })
            break
          case 'assistant_message':
            mutate((prev) => {
              const out = [...prev]
              const last = out[out.length - 1]
              if (last && (last.kind === 'assistant' || last.kind === 'reasoning') && last.streaming) {
                out[out.length - 1] = { ...last, streaming: false }
              }
              return out
            })
            break
          case 'tool_start':
            mutate((prev) => {
              const out = [...prev]
              const last = out[out.length - 1]
              if (last && (last.kind === 'assistant' || last.kind === 'reasoning') && last.streaming) {
                out[out.length - 1] = { ...last, streaming: false }
              }
              out.push({ kind: 'tool', id: uid(), callId: ev.id, name: ev.name, args: ev.args, output: null, ok: null })
              return out
            })
            break
          case 'tool_result':
            mutate((prev) => prev.map((it) =>
              it.kind === 'tool' && it.callId === ev.id
                ? { ...it, output: ev.output, ok: ev.ok }
                : it,
            ))
            break
          case 'error':
            mutate((prev) => [...prev, { kind: 'error', id: uid(), message: ev.message }])
            break
          case 'turn_end':
          case 'done':
            break
        }
      }, ac.signal)
      // source of truth after the turn
      await loadSession(sid)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setErrorBanner((e as Error).message)
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
      refreshSessions()
      refreshTree(sid)
    }
  }

  function stop() {
    abortRef.current?.abort()
  }

  // ------------------------------------------------------------ sessions
  async function newSession() {
    if (streaming) stop()
    const s = await api.createSession()
    setSid(s.id)
    setItems([])
    setTree([])
    closeFile()
    refreshSessions()
  }

  async function selectSession(id: string) {
    if (streaming) stop()
    setSid(id)
    setFileSel(null); setFileContent(null)
    await loadSession(id)
    refreshTree(id)
  }

  async function deleteSession(id: string) {
    await api.deleteSession(id)
    if (id === sid) await newSession()
    refreshSessions()
  }

  // --------------------------------------------------------------- files
  async function openFile(path: string) {
    if (!sid) return
    try {
      const f = await api.readFile(sid, path)
      setFileSel(path)
      setFileContent(f.binary ? '// (file nhị phân — không xem được)' : f.content)
      setFileDirty(false)
    } catch (e) { setErrorBanner(String(e)) }
  }

  function closeFile() { setFileSel(null); setFileContent(null); setFileDirty(false) }

  async function saveFile() {
    if (!sid || fileSel === null || fileContent === null) return
    await api.saveFile(sid, fileSel, fileContent)
    setFileDirty(false)
    refreshTree(sid)
  }

  async function deleteFile() {
    if (!sid || !fileSel) return
    if (!confirm(`Xóa ${fileSel}?`)) return
    await api.deleteFile(sid, fileSel)
    closeFile()
    refreshTree(sid)
  }

  async function newFile() {
    if (!sid) return
    const p = prompt('Đường dẫn file mới:', 'untitled.py')
    if (!p) return
    await api.saveFile(sid, p, '')
    refreshTree(sid)
    openFile(p)
  }

  // ------------------------------------------------------------- settings
  async function saveSettings(apiKey?: string, model?: string) {
    const s = await api.saveSettings(apiKey, model)
    setSettings(s)
  }

  // ---------------------------------------------------------------- render
  return (
    <div className="app">
      {settings && (
        <Sidebar
          sessions={sessions}
          currentId={sid}
          onSelect={selectSession}
          onNew={newSession}
          onDelete={deleteSession}
          demo={settings.demo}
          model={settings.model}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      )}

      <main className="chat-pane">
        <div className="chat-scroll" ref={chatScrollRef}>
          {items.length === 0 && (
            <div className="hero">
              <div className="hero-logo">⚡</div>
              <h1>Forge Agent</h1>
              <p>AI coding agent chạy trên máy bạn — đọc/ghi file, chạy lệnh, tự sửa lỗi.</p>
              <div className="hero-examples">
                {['Viết game snake bằng HTML/JS rồi mở thử', 'Phân tích dữ liệu csv trong workspace', 'Tạo REST API Python đơn giản + test'].map((x) => (
                  <button key={x} onClick={() => setInput(x)}>{x}</button>
                ))}
              </div>
            </div>
          )}
          {items.map((it) => {
            if (it.kind === 'user') {
              return (
                <div key={it.id} className="msg user">
                  <div className="bubble">{it.text}</div>
                </div>
              )
            }
            if (it.kind === 'assistant') {
              return (
                <div key={it.id} className="msg assistant">
                  <div className="who">⚡ Forge{it.streaming && <span className="cursor">▍</span>}</div>
                  <Markdown text={it.text} />
                </div>
              )
            }
            if (it.kind === 'reasoning') {
              return it.text.trim() ? (
                <details key={it.id} className="reasoning" open={it.streaming}>
                  <summary>💭 Suy nghĩ{it.streaming ? '…' : ''}</summary>
                  <div className="reasoning-body">{it.text}</div>
                </details>
              ) : null
            }
            if (it.kind === 'tool') return <div key={it.id} className="msg tool-wrap"><ToolCard item={it} /></div>
            return (
              <div key={it.id} className="msg error-msg">⚠ {it.message}</div>
            )
          })}
          {errorBanner && <div className="msg error-msg">⚠ {errorBanner}</div>}
        </div>

        <div className="composer">
          {settings?.demo && (
            <div className="demo-banner">
              DEMO MODE — chưa có OpenRouter API key. Agent vẫn chạy tool thật, nhưng "não" là kịch bản mẫu. Nhập key ở ⚙ để kích hoạt model thật.
            </div>
          )}
          <div className="composer-row">
            <textarea
              value={input}
              placeholder={streaming ? 'Agent đang làm việc…' : 'Nhập nhiệm vụ… (Enter gửi · Shift+Enter xuống dòng)'}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
              }}
              rows={Math.min(6, input.split('\n').length)}
            />
            {streaming
              ? <button className="btn-stop" onClick={stop}>■ Dừng</button>
              : <button className="btn-send" onClick={send} disabled={!input.trim()}>Gửi ➤</button>}
          </div>
          <div className="composer-foot">
            <span>Phiên: <code>{sid ?? '—'}</code></span>
            <span>Model: <code>{settings?.model ?? '—'}</code></span>
          </div>
        </div>
      </main>

      <FilesPane
        tree={tree}
        selected={fileSel}
        content={fileContent}
        dirty={fileDirty}
        onOpen={openFile}
        onChange={(c) => { setFileContent(c); setFileDirty(true) }}
        onSave={saveFile}
        onDelete={deleteFile}
        onRefresh={() => sid && refreshTree(sid)}
        onNewFile={newFile}
      />

      {settingsOpen && settings && (
        <SettingsModal
          settings={settings}
          onClose={() => setSettingsOpen(false)}
          onSave={saveSettings}
        />
      )}
    </div>
  )
}
