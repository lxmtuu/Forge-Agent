import React from 'react'
import type { SessionSummary } from '../types'

function relTime(ts: number): string {
  const d = Date.now() / 1000 - ts
  if (d < 60) return 'vừa xong'
  if (d < 3600) return `${Math.floor(d / 60)}p trước`
  if (d < 86400) return `${Math.floor(d / 3600)}h trước`
  return `${Math.floor(d / 86400)} ngày trước`
}

export function Sidebar(props: {
  sessions: SessionSummary[]
  currentId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  demo: boolean
  model: string
  onOpenSettings: () => void
}) {
  const [q, setQ] = React.useState('')
  const shown = props.sessions.filter((s) => {
    const t = q.trim().toLowerCase()
    return !t || s.title.toLowerCase().includes(t)
  })
  return (
    <aside className="sidebar">
      <div className="brand">
        <svg width="22" height="22" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#1f1f24" /><path d="M18.5 4 8 18h6.5L13 28 24 13.5h-6.5L18.5 4z" fill="#d97757" /></svg>
        <span>Forge <em>agent</em></span>
      </div>

      <button className="btn-primary" onClick={props.onNew}>＋ Phiên mới</button>

      <input
        className="session-search"
        placeholder="🔍 Tìm phiên…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="session-list">
        {shown.length === 0 && <div className="empty">{q ? 'Không khớp phiên nào' : 'Chưa có phiên nào'}</div>}
        {shown.map((s) => (
          <div
            key={s.id}
            className={`session-item ${s.id === props.currentId ? 'active' : ''}`}
            onClick={() => props.onSelect(s.id)}
          >
            <div className="session-title">{s.title}</div>
            <div className="session-meta">
              {s.message_count} tin · {relTime(s.updated_at)}
            </div>
            <button
              className="session-del"
              title="Xóa phiên"
              onClick={(e) => { e.stopPropagation(); props.onDelete(s.id) }}
            >✕</button>
          </div>
        ))}
      </div>

      <div className="sidebar-foot">
        <div className="model-badge" title="Model đang dùng">
          ⚡ {props.model || '—'}
        </div>
        {props.demo && <div className="demo-badge">DEMO (chưa có key)</div>}
        <button className="btn-ghost" onClick={props.onOpenSettings}>⚙ Cài đặt</button>
      </div>
    </aside>
  )
}
