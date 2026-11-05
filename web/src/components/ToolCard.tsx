import React, { useState } from 'react'
import type { Item } from '../types'
import { DiffView } from './DiffView'
import { useI18n } from '../i18n'

const TOOL_META: Record<string, { icon: string; label: [string, string] }> = {
  list_dir: { icon: '📂', label: ['Liệt kê thư mục', 'List directory'] },
  read_file: { icon: '📖', label: ['Đọc file', 'Read file'] },
  write_file: { icon: '📝', label: ['Ghi file', 'Write file'] },
  edit_file: { icon: '✂️', label: ['Sửa file', 'Edit file'] },
  search_files: { icon: '🔍', label: ['Tìm kiếm', 'Search files'] },
  run_command: { icon: '⌨️', label: ['Chạy lệnh', 'Run command'] },
}

function argSummary(name: string, args: Record<string, unknown>): string {
  if (name === 'run_command') return String(args.command ?? '')
  if (name === 'write_file' || name === 'edit_file' || name === 'read_file') return String(args.path ?? '')
  if (name === 'search_files') return String(args.query ?? '')
  if (name === 'list_dir') return String(args.path ?? '.')
  return JSON.stringify(args).slice(0, 80)
}

export function ToolCard({ item }: { item: Extract<Item, { kind: 'tool' }> }) {
  const { t } = useI18n()
  const hasDiff = Boolean(item.diff)
  const [open, setOpen] = useState(hasDiff)
  const meta = TOOL_META[item.name] ?? { icon: '🔧', label: [item.name, item.name] as [string, string] }
  const running = item.output === null

  const diffLines = hasDiff
    ? (item.diff as string).split('\n').filter((l) => l.startsWith('+') && !l.startsWith('+++')).length
    : 0
  const delLines = hasDiff
    ? (item.diff as string).split('\n').filter((l) => l.startsWith('-') && !l.startsWith('---')).length
    : 0

  return (
    <div className={`tool-card ${running ? 'running' : item.ok ? 'ok' : 'fail'}`}>
      <button className="tool-head" onClick={() => setOpen(!open)}>
        <span className="tool-icon">{running ? <span className="spinner" /> : meta.icon}</span>
        <span className="tool-label">{t(...meta.label)}</span>
        <code className="tool-arg">{argSummary(item.name, item.args)}</code>
        {hasDiff && <span className="diff-badge"><em className="d-add">+{diffLines}</em> <em className="d-del">−{delLines}</em></span>}
        <span className={`tool-status ${item.ok === false ? 'bad' : ''}`}>
          {running ? t('đang chạy…', 'running…') : item.ok ? '✓' : t('✗ lỗi', '✗ failed')}
        </span>
        <span className={`chev ${open ? 'up' : ''}`}>▾</span>
      </button>
      {open && (
        <div className="tool-body">
          {hasDiff && (
            <div className="tool-diff">
              <div className="mini-label">{t('Thay đổi', 'Changes')}</div>
              <DiffView diff={item.diff as string} />
            </div>
          )}
          {Object.keys(item.args).length > 0 && (
            <div className="tool-args">
              <div className="mini-label">{t('Tham số', 'Arguments')}</div>
              <pre>{JSON.stringify(item.args, null, 2).slice(0, 4000)}</pre>
            </div>
          )}
          {item.output !== null && (
            <div className="tool-out">
              <div className="mini-label">{t('Kết quả', 'Result')}</div>
              <pre>{item.output.slice(0, 8000) || t('(rỗng)', '(empty)')}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
