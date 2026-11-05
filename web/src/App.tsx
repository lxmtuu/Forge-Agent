import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { uid } from './types'
import type { AgentEvent, BatchEvent, ChatMode, FileNode, Item, SessionSummary, Settings, TaskGroup, Usage } from './types'
import { Sidebar } from './components/Sidebar'
import { FilesPane } from './components/FilesPane'
import { SettingsModal } from './components/SettingsModal'
import { ToolCard } from './components/ToolCard'
import { ApprovalCard } from './components/ApprovalCard'
import type { ContextStats } from './types'
import { ElicitationCard } from './components/ElicitationCard'
import { Markdown } from './md'

/** Pure reducer: apply one agent event to an item timeline. */
function applyEvent(prev: Item[], ev: AgentEvent): Item[] {
  switch (ev.type) {
    case 'reasoning_delta': {
      const last = prev[prev.length - 1]
      if (last && last.kind === 'reasoning' && last.streaming) {
        return [...prev.slice(0, -1), { ...last, text: last.text + ev.text }]
      }
      return [...prev, { kind: 'reasoning', id: uid(), text: ev.text, streaming: true }]
    }
    case 'assistant_delta': {
      const last = prev[prev.length - 1]
      if (last && last.kind === 'assistant' && last.streaming) {
        return [...prev.slice(0, -1), { ...last, text: last.text + ev.text }]
      }
      return [...prev, { kind: 'assistant', id: uid(), text: ev.text, streaming: true }]
    }
    case 'assistant_message': {
      const out = [...prev]
      const last = out[out.length - 1]
      if (last && (last.kind === 'assistant' || last.kind === 'reasoning') && last.streaming) {
        out[out.length - 1] = { ...last, streaming: false }
      }
      return out
    }
    case 'tool_start': {
      const out = [...prev]
      const last = out[out.length - 1]
      if (last && (last.kind === 'assistant' || last.kind === 'reasoning') && last.streaming) {
        out[out.length - 1] = { ...last, streaming: false }
      }
      out.push({ kind: 'tool', id: uid(), callId: ev.id, name: ev.name, args: ev.args, output: null, ok: null })
      return out
    }
    case 'tool_result':
      return prev.map((it) =>
        it.kind === 'tool' && it.callId === ev.id
          ? { ...it, output: ev.output, ok: ev.ok, diff: ev.diff }
          : it,
      )
    case 'approval_request':
      return [...prev, {
        kind: 'approval', id: uid(), approvalId: ev.id, command: ev.command,
        level: ev.level, reasons: ev.reasons, decision: null,
      }]
    case 'subagent_started':
      return [...prev, { kind: 'subagent', id: uid(), saId: ev.id, task: ev.task,
                         sessionId: ev.session_id, tools: 0, status: 'running' as const,
                         model: ev.model }]
    case 'model_fallback':
      return [...prev, { kind: 'notice', id: uid(),
                         text: `🔁 Model lỗi — chuyển từ ${ev.from} → ${ev.to}` }]
    case 'todo_update': {
      const idx = prev.findIndex((it) => it.kind === 'todo')
      const card: Item = { kind: 'todo', id: idx >= 0 ? (prev[idx] as { id: string }).id : uid(), items: ev.items }
      if (idx >= 0) return [...prev.slice(0, idx), card, ...prev.slice(idx + 1)]
      return [...prev, card]
    }
    case 'subagent_progress':
      return prev.map((it) => it.kind === 'subagent' && it.saId === ev.id
        ? { ...it, tools: ev.tools } : it)
    case 'subagent_done':
      return prev.map((it) => it.kind === 'subagent' && it.saId === ev.id
        ? { ...it, status: 'done' as const, tools: ev.tools } : it)
    case 'subagent_output':
      return prev.map((it) => it.kind === 'subagent' && it.saId === ev.id
        ? { ...it, status: 'done' as const, output: ev.output } : it)
    case 'elicitation_request':
      return [...prev, {
        kind: 'elicitation', id: uid(), eid: ev.id, server: ev.server ?? '?',
        message: ev.message ?? '', schema: ev.schema ?? null, url: ev.url ?? null,
        action: null,
      }]
    case 'approval_decision':
      return prev.map((it) =>
        it.kind === 'approval' && it.approvalId === ev.id
          ? { ...it, decision: ev.decision }
          : it,
      )
    case 'error':
      return [...prev, { kind: 'error', id: uid(), message: ev.message }]
    default:
      return prev
  }
}

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
  const [parallel, setParallel] = useState(false)
  const [batch, setBatch] = useState<TaskGroup[] | null>(null)
  const [sessionUsage, setSessionUsage] = useState<Usage | null>(null)
  const [chatMode, setChatMode] = useState<ChatMode>('agent')
  const [battleModels, setBattleModels] = useState('openrouter/free, google/gemini-3.8-flash, deepseek/deepseek-v4.1-flash')
  const [info, setInfo] = useState<string | null>(null)
  const [busyTool, setBusyTool] = useState<string | null>(null)
  const [pendingImages, setPendingImages] = useState<string[]>([])
  const [ctx, setCtx] = useState<ContextStats | null>(null)
  const [showSb, setShowSb] = useState(false)
  const [queued, setQueued] = useState<string[]>([])
  const [menu, setMenu] = useState<{ kind: 'cmd' | 'file'; items: string[]; sel: number } | null>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  const WEB_COMMANDS: [string, string][] = [
    ['/review', 'code review diff thật — P0–P3 + verdict, chỉ đọc'],
    ['/diff', 'xem diff phiên (git repo hoặc checkpoint)'],
    ['/memory', 'xem bộ nhớ đang nạp · “/memory clear” để xoá'],
    ['/run', 'chạy custom agent từ .forge/agents/<tên>.md'],
    ['/skills', 'quản lý skill chuẩn SKILL.md · /skills add <git|thư-mục> · new · remove'],
  ]
  const queuedRef = useRef<string[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const nearBottomRef = useRef(true)
  const [showJump, setShowJump] = useState(false)

  function onChatScroll() {
    const el = chatScrollRef.current
    if (!el) return
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 130
    setShowJump(!nearBottomRef.current)
  }

  function jumpToBottom() {
    const el = chatScrollRef.current
    if (el) { el.scrollTop = el.scrollHeight; nearBottomRef.current = true; setShowJump(false) }
  }

  const flatFiles = useMemo(() => {
    const out: string[] = []
    const walk = (nodes: FileNode[], pre: string) => {
      for (const n of nodes) {
        const path = pre ? `${pre}/${n.name}` : n.name
        if (n.type === 'dir') walk(n.children ?? [], path)
        else out.push(path)
      }
    }
    walk(tree, '')
    return out
  }, [tree])

  function updateInput(v: string) {
    setInput(v)
    const mCmd = v.match(/^\/([a-z0-9_-]*)$/)
    if (mCmd) {
      const q = mCmd[1].toLowerCase()
      const items = WEB_COMMANDS.filter(([c]) => c.slice(1).startsWith(q)).map(([c]) => c)
      setMenu(items.length ? { kind: 'cmd', items, sel: 0 } : null)
      return
    }
    const mAt = v.match(/(?:^|\s)@([^\s@]*)$/)
    if (mAt) {
      const q = mAt[1].toLowerCase()
      const items = flatFiles.filter((f) => f.toLowerCase().includes(q)).slice(0, 8)
      setMenu(items.length ? { kind: 'file', items, sel: 0 } : null)
      return
    }
    setMenu(null)
  }

  function applyMenu(item: string) {
    if (!menu) return
    if (menu.kind === 'cmd') setInput(item + ' ')
    else setInput((cur) => cur.replace(/@[^\s@]*$/, `@${item} `))
    setMenu(null)
    setTimeout(() => taRef.current?.focus(), 0)
  }

  const refreshSessions = useCallback(() => {
    api.listSessions().then(setSessions).catch(() => {})
  }, [])

  const loadSession = useCallback(async (id: string) => {
    try {
      const s = await api.getSession(id)
      setItems(buildTimeline(s.messages ?? []))
      setSessionUsage(s.usage ?? null)
      setBatch(null)
      api.context(id).then(setCtx).catch(() => {})
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

  const refreshCtx = (sessionId: string | null) => {
    if (!sessionId) { setCtx(null); return }
    api.context(sessionId).then(setCtx).catch(() => {})
  }

  // autoscroll while streaming — chỉ khi người dùng đang ở gần đáy (tôn trọng cuộn tay)
  useEffect(() => {
    const el = chatScrollRef.current
    if (el && nearBottomRef.current) el.scrollTop = el.scrollHeight
  }, [items, batch])

  // ------------------------------------------------------------------ send
  async function send(textArg?: string) {
    const text = (textArg ?? input).trim()
    if (!text || !sid) return
    if (streaming) { enqueue(text); return }
    setInput('')
    setErrorBanner(null)
    setBatch(null)
    const ac = new AbortController()
    abortRef.current = ac
    setStreaming(true)

    try {
      if (parallel || chatMode === 'battle') {
        const isBattle = chatMode === 'battle'
        const prompts = isBattle ? [text] : text.split('\n').map((s) => s.trim()).filter(Boolean).slice(0, 5)
        if (!prompts.length) return
        setItems([])
        if (isBattle) {
          const models = battleModels.split(',').map((s) => s.trim()).filter(Boolean).slice(0, 4)
          if (!models.length) { setErrorBanner('Battle cần ít nhất 1 model'); return }
          setBatch(models.map((m, i) => ({
            index: i, sessionId: '', title: m, status: 'running' as const,
            items: [{ kind: 'user', id: uid(), text } as Item],
          })))
        } else {
          setBatch(prompts.map((p, i) => ({
            index: i, sessionId: '', title: p, status: 'running' as const,
            items: [{ kind: 'user', id: uid(), text: p } as Item],
          })))
        }
        const onBatch = (ev: BatchEvent) => {
          if (ev.type === 'task_created') {
            setBatch((prev) => prev?.map((g) => g.index === ev.index ? { ...g, sessionId: ev.session_id } : g) ?? null)
          } else if (ev.type === 'task_event') {
            setBatch((prev) => prev?.map((g) => {
              if (g.index !== ev.index) return g
              const inner = ev.event
              const next: TaskGroup = { ...g, items: applyEvent(g.items, inner as AgentEvent) }
              if (inner.type === 'task_done') next.status = 'done'
              if (inner.type === 'error') next.status = 'error'
              return next
            }) ?? null)
          } else if (ev.type === 'batch_done') {
            setBatch((prev) => prev?.map((g) => ({ ...g, status: g.status === 'error' ? 'error' : 'done' })) ?? null)
          } else if (ev.type === 'error') {
            setErrorBanner(ev.message)
          }
        }
        if (isBattle) await api.battleStream(text, battleModels.split(',').map((s) => s.trim()).filter(Boolean), onBatch, ac.signal)
        else await api.batchStream(prompts, onBatch, ac.signal)
      } else {
        setItems((prev) => [...prev, { kind: 'user', id: uid(), text, images: pendingImages.length ? pendingImages : undefined }])
        const imgs = pendingImages
        setPendingImages([])
        await api.streamChat(sid, text, chatMode, (ev: AgentEvent) => {
          if (ev.type === 'turn_end') {
            if (ev.session_usage) setSessionUsage(ev.session_usage)
            return
          }
          setItems((prev) => applyEvent(prev, ev))
        }, ac.signal, imgs)
        await loadSession(sid)
        refreshCtx(sid)
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setErrorBanner((e as Error).message)
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
      refreshSessions()
      refreshTree(sid)
      const [next, ...rest] = queuedRef.current
      if (next !== undefined) {
        queuedRef.current = rest
        setQueued(rest)
        setTimeout(() => { void send(next) }, 80)
      }
    }
  }

  function stop() {
    abortRef.current?.abort()
  }

  function enqueue(text: string) {
    queuedRef.current = [...queuedRef.current, text]
    setQueued(queuedRef.current)
  }

  function unqueue(i: number) {
    queuedRef.current = queuedRef.current.filter((_, j) => j !== i)
    setQueued(queuedRef.current)
  }

  // ------------------------------------------------------------ sessions
  async function newSession() {
    if (streaming) stop()
    const s = await api.createSession()
    setSid(s.id)
    setItems([])
    setBatch(null)
    setSessionUsage(null)
    setTree([])
    closeFile()
    refreshSessions()
  }

  async function selectSession(id: string) {
    if (streaming) stop()
    setShowSb(false)
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

  async function uploadFiles(fs: FileList | null) {
    if (!sid || !fs || fs.length === 0) return
    try {
      const r = await api.uploadFiles(sid, Array.from(fs))
      if (r.skipped.length) setErrorBanner(`Bỏ qua: ${r.skipped.join(', ')}`)
      refreshTree(sid)
    } catch (e) { setErrorBanner(String(e)) }
  }

  function exportWorkspace() {
    if (sid) window.open(api.exportUrl(sid), '_blank')
  }

  // ---------------------------------------------------- comfort tools
  function pickImages(files: FileList | null) {
    if (!files || !files.length) return
    const picks = Array.from(files).slice(0, 4 - pendingImages.length)
    for (const f of picks) {
      if (!f.type.startsWith('image/')) continue
      if (f.size > 4 * 1024 * 1024) { setErrorBanner(`Ảnh ${f.name} > 4MB — hãy thu nhỏ trước`); continue }
      const rd = new FileReader()
      rd.onload = () => { if (typeof rd.result === 'string') setPendingImages((p) => p.length >= 4 ? p : [...p, rd.result as string]) }
      rd.readAsDataURL(f)
    }
  }

  async function doFork() {
    if (!sid || streaming || busyTool) return
    setBusyTool('fork')
    try {
      const r = await api.fork(sid)
      if (r.session?.id) {
        setSid(r.session.id); await loadSession(r.session.id); refreshSessions(); refreshTree(r.session.id)
        setInfo(`🍴 Đã fork → phiên mới ${r.session.id}`)
      }
    } catch (e) { setErrorBanner(String(e)) }
    finally { setBusyTool(null) }
  }

  async function doUndo() {
    if (!sid || streaming || busyTool) return
    setBusyTool('undo')
    try {
      const r = await api.undo(sid)
      if (r.ok) { await loadSession(sid); refreshTree(sid); setInfo('↩ ' + r.message) }
      else setErrorBanner(r.message)
    } catch (e) { setErrorBanner(String(e)) }
    finally { setBusyTool(null) }
  }

  async function doCompact() {
    if (!sid || streaming || busyTool) return
    setBusyTool('compact')
    try {
      const r = await api.compact(sid)
      if (r.ok) { await loadSession(sid); refreshCtx(sid); setInfo(`🧹 Đã nén ${r.before} → ${r.after} tin nhắn`) }
      else setErrorBanner(r.message ?? 'Không nén được')
    } catch (e) { setErrorBanner(String(e)) }
    finally { setBusyTool(null) }
  }

  async function doInit() {
    if (!sid || busyTool) return
    setBusyTool('init')
    try {
      const r = await api.initAgents(sid)
      if (r.ok) { refreshTree(sid); setInfo('🚀 Đã tạo AGENTS.md') }
      else setErrorBanner(r.message ?? 'Không tạo được AGENTS.md')
    } catch (e) { setErrorBanner(String(e)) }
    finally { setBusyTool(null) }
  }

  // ------------------------------------------------------------- settings
  async function saveSettings(apiKey?: string, model?: string, patch?: { approval_mode?: string; docker_sandbox?: boolean; max_tokens?: number }) {
    const s = await api.saveSettings(apiKey, model, patch)
    setSettings(s)
  }

  // --------------------------------------------------------------- render
  function renderItem(it: Item) {
    if (it.kind === 'user') {
      return (
        <div key={it.id} className="msg user">
          <div className="bubble">
            {it.images && it.images.length > 0 && (
              <div className="msg-images">
                {it.images.map((src, i) => <img key={i} src={src} alt={`ảnh ${i + 1}`} />)}
              </div>
            )}
            {it.text}
          </div>
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
    if (it.kind === 'subagent') {
      return (
        <div key={it.id} className="msg tool-wrap">
          <div className={`tool-card ${it.status === 'running' ? 'running' : 'ok'}`}>
            <div className="tool-head">
              <span className="tool-icon">{it.status === 'running' ? <span className="spinner" /> : '🧩'}</span>
              <span className="tool-label">Sub-agent{it.model && it.model !== 'inherit' ? ` · ${it.model}` : ''}</span>
              <code className="tool-arg">{it.task.slice(0, 60)}</code>
              <span className="tool-status">{it.status === 'running' ? `${it.tools} tools…` : 'xong'}</span>
            </div>
            {it.output && (
              <div className="tool-body"><pre>{it.output.slice(0, 4000)}</pre></div>
            )}
          </div>
        </div>
      )
    }
    if (it.kind === 'elicitation') {
      return (
        <ElicitationCard
          key={it.id}
          item={it}
          onResolve={(eid, action, content) => {
            api.elicitation(eid, action, content).catch(() => {})
            setItems((prev) => prev.map((x) =>
              x.kind === 'elicitation' && x.eid === eid ? { ...x, action } : x))
          }}
        />
      )
    }
    if (it.kind === 'approval') {
      return (
        <div key={it.id} className="msg tool-wrap">
          <ApprovalCard
            item={it}
            onResolved={(approvalId, decision) => {
              setItems((prev) => prev.map((x) =>
                x.kind === 'approval' && x.approvalId === approvalId ? { ...x, decision } : x))
            }}
          />
        </div>
      )
    }
    if (it.kind === 'todo') {
      const done = it.items.filter((x) => x.status === 'done').length
      return (
        <div key={it.id} className="msg tool-wrap">
          <div className={`tool-card ${done === it.items.length && it.items.length > 0 ? 'ok' : ''}`}>
            <div className="tool-head">
              <span className="tool-icon">📋</span>
              <span className="tool-label">Tiến độ</span>
              <code className="tool-arg">{done}/{it.items.length} việc xong</code>
              <span className="tool-status">{done === it.items.length ? 'hoàn tất' : 'đang làm'}</span>
            </div>
            <div className="tool-body todo-list">
              {it.items.map((x, i) => (
                <div key={i} className={`todo-row st-${x.status}`}>
                  <span className="todo-mark">{x.status === 'done' ? '✅' : x.status === 'doing' ? '▶' : '◻'}</span>
                  <span className={x.status === 'done' ? 'todo-done' : ''}>{x.text}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )
    }
    if (it.kind === 'notice') return <div key={it.id} className="msg sys-msg">{it.text}</div>
    return <div key={it.id} className="msg error-msg">⚠ {it.message}</div>
  }

  return (
    <div className={`app ${showSb ? 'show-sb' : ''}`}>
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
        <button className="sb-toggle" aria-label="Danh sách phiên"
          onClick={() => setShowSb((v) => !v)}>☰</button>
        <div className="chat-scroll" ref={chatScrollRef} onScroll={onChatScroll}>
          {items.length === 0 && !batch && (
            <div className="hero">
              <div className="hero-logo">⚡</div>
              <h1>Forge Agent</h1>
              <p>AI coding agent chạy trên máy bạn — đọc/ghi file, chạy lệnh, tự sửa lỗi.</p>
              <div className="hero-examples">
                {['Viết game snake bằng HTML/JS rồi mở thử', 'Phân tích dữ liệu csv trong workspace', 'Tạo REST API Python đơn giản + test'].map((x) => (
                  <button key={x} onClick={() => setInput(x)}>{x}</button>
                ))}
              </div>
              <div className="hero-tips" aria-label="Mẹo nhanh">
                <span><code>/review</code> review diff</span>
                <span><code>/diff</code> xem thay đổi</span>
                <span><code>/memory</code> bộ nhớ</span>
                <span><code># ghi chú</code> ghi nhớ nhanh</span>
                <span><code>@file.py</code> đính file</span>
                <span><code>/run tên</code> custom agent</span>
              </div>
            </div>
          )}
          {items.map(renderItem)}
          {batch && batch.map((g) => (
            <div key={`g${g.index}`} className="batch-group">
              <div className="batch-head">
                <span className={`st ${g.status === 'done' ? 'st-ok' : g.status === 'error' ? 'st-bad' : 'st-warn'}`}>
                  {g.status === 'running' ? 'đang chạy…' : g.status}
                </span>
                <b>Task {g.index + 1}</b>
                <span className="batch-title">{g.title.replace(/^⚔ [^:]+: /, '')}</span>
                {/⚔ /.test(g.title) && <span className="model-tag">{g.title.replace(/^⚔ ([^:]+):.*/, '$1')}</span>}
                {g.sessionId && <code className="batch-sid">{g.sessionId}</code>}
              </div>
              <div className="batch-body">{g.items.map(renderItem)}</div>
            </div>
          ))}
          {errorBanner && (
            <div className="msg error-msg">
              <span className="error-text">⚠ {errorBanner}</span>
              <button className="error-dismiss" title="Đóng" onClick={() => setErrorBanner(null)}>✕</button>
            </div>
          )}
          {info && (
            <div className="msg info-msg">
              <span className="error-text">{info}</span>
              <button className="error-dismiss" title="Đóng" onClick={() => setInfo(null)}>✕</button>
            </div>
          )}
        </div>

        {showJump && (
          <button className="scroll-bottom" onClick={jumpToBottom} title="Xuống cuối">↓</button>
        )}

        <div className="composer">
          {settings?.demo && (
            <div className="demo-banner">
              DEMO MODE — chưa có OpenRouter API key. Agent vẫn chạy tool thật, nhưng "não" là kịch bản mẫu. Nhập key ở ⚙ để kích hoạt model thật.
            </div>
          )}
          <div className="mode-chips">
            {([
              ['direct', '💬', 'Trực tiếp', 'Chat thuần — không dùng tool, nhanh và rẻ'],
              ['agent', '🤖', 'Agent', 'Vòng lặp đầy đủ: đọc/ghi file, chạy lệnh, tự sửa lỗi'],
              ['plan', '📋', 'Kế hoạch', 'Chỉ đọc + xuất kế hoạch, không sửa gì — duyệt xong chuyển Agent'],
              ['battle', '⚔', 'Battle', 'Cùng 1 prompt chạy N model song song, chọn phiên thắng'],
            ] as [ChatMode, string, string, string][]).map(([m, icon, label, tip]) => (
              <button key={m} className={`mode-chip ${chatMode === m ? 'on' : ''}`} title={tip}
                onClick={() => setChatMode(m)}>{icon} {label}</button>
            ))}
            <span className="mode-sep" />
            <button className={`mode-chip ${parallel ? 'on' : ''}`}
              title="Mỗi dòng trong ô nhập là 1 tác vụ song song (không phụ thuộc chế độ trên)"
              onClick={() => setParallel(!parallel)}>⚡ Song song</button>
          </div>
          {chatMode === 'battle' && (
            <input className="battle-models" value={battleModels}
              onChange={(e) => setBattleModels(e.target.value)}
              placeholder="Các model thi đấu, cách nhau bằng dấu phẩy (tối đa 4)" />
          )}
          {queued.length > 0 && (
            <div className="queued-list">
              {queued.map((q, i) => (
                <span key={i} className="queued-pill" title="Sẽ tự gửi khi lượt hiện tại xong">
                  ⏳ {q.slice(0, 60)}
                  <button className="queued-x" title="Bỏ khỏi hàng đợi" onClick={() => unqueue(i)}>✕</button>
                </span>
              ))}
            </div>
          )}
          {menu && (
            <div className="cmd-menu" role="listbox" aria-label="Gợi ý lệnh">
              {menu.items.map((it, i) => (
                <button key={it} role="option" aria-selected={i === menu.sel}
                  className={`cmd-item ${i === menu.sel ? 'on' : ''}`}
                  onMouseDown={(e) => { e.preventDefault(); applyMenu(it) }}>
                  <code>{it}</code>
                  {menu.kind === 'cmd' && (
                    <span>{WEB_COMMANDS.find(([c]) => c === it)?.[1] ?? ''}</span>
                  )}
                </button>
              ))}
              {menu.kind === 'cmd' && (
                <div className="cmd-foot">Lệnh tuỳ chỉnh .forge/commands/&lt;tên&gt;.md cũng gọi được: /&lt;tên&gt;</div>
              )}
            </div>
          )}
          <div className="composer-row">
            <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple
              style={{ display: 'none' }} id="img-picker"
              onChange={(e) => { pickImages(e.target.files); e.target.value = '' }} />
            <button className="btn-attach" title="Đính kèm ảnh (tối đa 4 — model phải hỗ trợ vision)"
              onClick={() => document.getElementById('img-picker')?.click()} disabled={streaming || pendingImages.length >= 4}>📎</button>
            <textarea
              ref={taRef}
              value={input}
              placeholder={streaming
                ? 'Agent đang làm việc…'
                : chatMode === 'battle'
                  ? 'Nhiệm vụ thi đấu… (Enter gửi)'
                  : parallel
                    ? 'Mỗi dòng = 1 tác vụ song song · Ctrl+Enter để chạy'
                    : chatMode === 'direct' ? 'Hỏi gì đó… (Enter gửi)'
                      : chatMode === 'plan' ? 'Mô tả tính năng cần lập kế hoạch…'
                        : 'Nhập nhiệm vụ… (@file.py đính kèm file · Enter gửi · Shift+Enter xuống dòng)'}
              onChange={(e) => updateInput(e.target.value)}
              onKeyDown={(e) => {
                if (menu) {
                  if (e.key === 'ArrowDown') { e.preventDefault(); setMenu({ ...menu, sel: (menu.sel + 1) % menu.items.length }); return }
                  if (e.key === 'ArrowUp') { e.preventDefault(); setMenu({ ...menu, sel: (menu.sel - 1 + menu.items.length) % menu.items.length }); return }
                  if (e.key === 'Enter') { e.preventDefault(); applyMenu(menu.items[menu.sel]); return }
                  if (e.key === 'Escape') { setMenu(null); return }
                }
                if ((e.key === 'Enter' && !e.shiftKey && (!parallel || chatMode === 'battle')) ||
                    (e.key === 'Enter' && (e.ctrlKey || e.metaKey))) {
                  e.preventDefault()
                  if (streaming && input.trim()) { enqueue(input.trim()); setInput(''); updateInput('') }
                  else send()
                }
              }}
              rows={parallel && chatMode !== 'battle' ? Math.min(6, Math.max(3, input.split('\n').length)) : Math.min(6, input.split('\n').length)}
            />
            {streaming
              ? <button className="btn-stop" onClick={stop}>■ Dừng</button>
              : <button className="btn-send" onClick={() => send()} disabled={!input.trim()}>Gửi ➤</button>}
          </div>
          <div className="composer-foot">
            <span>Phiên: <code>{sid ?? '—'}</code></span>
            <span>Model: <code>{settings?.model ?? '—'}</code></span>
            {sessionUsage && <span>🔢 Tokens: <code>{sessionUsage.total_tokens ?? 0}</code> (↑{sessionUsage.prompt_tokens ?? 0} ↓{sessionUsage.completion_tokens ?? 0})</span>}
            {sessionUsage?.cost_usd != null && (
              <span title="Chi phí ước lượng theo giá OpenRouter — chỉ tính các lượt đã chạy trong phiên này">
                💵 <code>~${sessionUsage.cost_usd < 0.01 ? sessionUsage.cost_usd.toFixed(4) : sessionUsage.cost_usd.toFixed(2)}</code>
              </span>
            )}
            {ctx && <span className={`ctx-chip ${ctx.percent !== null && ctx.percent >= 90 ? 'ctx-danger' : ctx.percent !== null && ctx.percent >= 70 ? 'ctx-warn' : ''}`} title={`≈ ${ctx.est_tokens.toLocaleString()} tokens / giới hạn ${(ctx.limit || 0).toLocaleString()} ký tự · ${ctx.messages} tin nhắn${ctx.memory ? ' · có MEMORY.md' : ''}${ctx.percent !== null && ctx.percent >= 70 ? ' · nên /compact (nút 🧹)' : ''}`}>🧠 Context: <code>{ctx.percent !== null ? ctx.percent + '%' : '∞'}</code></span>}
            <span className="foot-actions">
              <button className="foot-btn" disabled={busyTool !== null} title="Hoàn tác thay đổi gần nhất của agent (checkpoint git nội bộ)" onClick={doUndo}>{busyTool === 'undo' ? '…' : '↩'} Undo</button>
              <button className="foot-btn" disabled={busyTool !== null} title="Nén hội thoại bằng LLM để giải phóng context" onClick={doCompact}>{busyTool === 'compact' ? '…' : '🧹'} Nén</button>
              <button className="foot-btn" disabled={busyTool !== null} title="Phân tích workspace và sinh AGENTS.md" onClick={doInit}>{busyTool === 'init' ? '…' : '🚀'} Init</button>
              <button className="foot-btn" disabled={busyTool !== null || !sid} title="Fork phiên: copy messages + workspace thành bản mới để thử hướng khác" onClick={doFork}>{busyTool === 'fork' ? '…' : '🍴'} Fork</button>
              <a className="foot-btn" href={sid ? `/api/sessions/${sid}/export` : '#'} download title="Tải hội thoại dạng Markdown" onClick={(e) => { if (!sid) e.preventDefault() }}>⤓ Export</a>
            </span>
          </div>
          {pendingImages.length > 0 && (
            <div className="pending-images">
              {pendingImages.map((src, i) => (
                <span key={i} className="pending-img">
                  <img src={src} alt={`ảnh ${i + 1}`} />
                  <button className="pending-x" title="Bỏ ảnh" onClick={() => setPendingImages((p) => p.filter((_, j) => j !== i))}>✕</button>
                </span>
              ))}
            </div>
          )}
        </div>
      </main>

      <FilesPane
        sid={sid ?? ''}
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
        onUpload={uploadFiles}
        onExport={exportWorkspace}
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
