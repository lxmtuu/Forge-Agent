import React from 'react'
import type { SessionSummary } from '../types'
import { useI18n, type Translate } from '../i18n'

function relTime(ts: number, t: Translate): string {
  const d = Date.now() / 1000 - ts
  if (d < 60) return t('vừa xong', 'just now')
  if (d < 3600) return t(`${Math.floor(d / 60)}p trước`, `${Math.floor(d / 60)}m ago`)
  if (d < 86400) return t(`${Math.floor(d / 3600)}h trước`, `${Math.floor(d / 3600)}h ago`)
  const days = Math.floor(d / 86400)
  return t(`${days} ngày trước`, `${days}d ago`)
}

export function Sidebar(props: {
  sessions: SessionSummary[]
  currentId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  demo: boolean
  model: string
  userEmail: string
  userRole: string
  onLogout: () => void
  onOpenSettings: () => void
  onClose?: () => void
}) {
  const { t } = useI18n()
  const [q, setQ] = React.useState('')
  const shown = props.sessions.filter((s) => {
    const query = q.trim().toLowerCase()
    return !query || s.title.toLowerCase().includes(query)
  })
  return (
    <aside className="sidebar" aria-label={t('Điều hướng phiên', 'Session navigation')}>
      <div className="brand">
        <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#1f1f24" /><path d="M18.5 4 8 18h6.5L13 28 24 13.5h-6.5L18.5 4z" fill="#d97757" /></svg>
        <span>Forge <em>agent</em></span>
        <button className="sidebar-close" aria-label={t('Đóng sidebar', 'Close sidebar')} onClick={props.onClose}>✕</button>
      </div>

      <button className="btn-primary" onClick={props.onNew}>{t('＋ Phiên mới', '＋ New session')}</button>

      <input
        className="session-search"
        aria-label={t('Tìm phiên', 'Search sessions')}
        placeholder={t('🔍 Tìm phiên…', '🔍 Search sessions…')}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="session-list">
        {shown.length === 0 && <div className="empty">{q ? t('Không khớp phiên nào', 'No matching sessions') : t('Chưa có phiên nào', 'No sessions yet')}</div>}
        {shown.map((s) => (
          <div key={s.id} className={`session-item ${s.id === props.currentId ? 'active' : ''}`}>
            <button className="session-main" onClick={() => props.onSelect(s.id)}
              aria-current={s.id === props.currentId ? 'page' : undefined}>
              <span className="session-title">{s.title}</span>
              <span className="session-meta">{t(`${s.message_count} tin`, `${s.message_count} ${s.message_count === 1 ? 'message' : 'messages'}`)} · {relTime(s.updated_at, t)}</span>
            </button>
            <button
              className="session-del"
              title={t(`Xóa phiên ${s.title}`, `Delete session ${s.title}`)}
              aria-label={t(`Xóa phiên ${s.title}`, `Delete session ${s.title}`)}
              onClick={() => props.onDelete(s.id)}
            >✕</button>
          </div>
        ))}
      </div>

      <div className="sidebar-foot">
        <div className="model-badge" title={t('Model đang dùng', 'Current model')}>
          ⚡ {props.model || '—'}
        </div>
        {props.demo && <div className="demo-badge">{t('DEMO (chưa có key)', 'DEMO (no key)')}</div>}
        <button className="btn-ghost" onClick={props.onOpenSettings}>{t('⚙ Cài đặt', '⚙ Settings')}</button>
        <div className="account-row" title={props.userEmail}>
          <span>👤 {props.userEmail}</span><em>{props.userRole}</em>
          <button className="btn-ghost btn-sm" onClick={props.onLogout}>{t('Đăng xuất', 'Log out')}</button>
        </div>
      </div>
    </aside>
  )
}
