import React, { useRef, useState } from 'react'
import { api } from '../api'
import type { FileNode } from '../types'

function TreeRow(props: {
  node: FileNode
  depth: number
  path: string
  selected: string | null
  onOpen: (p: string) => void
}) {
  const { node, depth, path, selected, onOpen } = props
  const [open, setOpen] = useState(depth < 2)
  if (node.type === 'dir') {
    return (
      <div>
        <button type="button" className="tree-row dir" style={{ paddingLeft: 8 + depth * 14 }}
          aria-expanded={open} onClick={() => setOpen(!open)}>
          <span className="chev-sm">{open ? '▾' : '▸'}</span> 📁 {node.name}
        </button>
        {open && (node.children ?? []).map((c) => (
          <TreeRow key={c.name + (c.path ?? '')} node={c} depth={depth + 1}
            path={path ? `${path}/${c.name}` : c.name} selected={selected} onOpen={onOpen} />
        ))}
      </div>
    )
  }
  const full = path
  return (
    <button type="button" className={`tree-row file ${selected === full ? 'active' : ''}`}
      style={{ paddingLeft: 8 + depth * 14 + 14 }} onClick={() => onOpen(full)}>
      📄 {node.name}
    </button>
  )
}

function Terminal({ sid }: { sid: string }) {
  const [cmd, setCmd] = useState('')
  const [out, setOut] = useState('')
  const [busy, setBusy] = useState(false)
  const histRef = useRef<string[]>([])
  const histIdx = useRef(-1)
  const outRef = useRef<HTMLPreElement>(null)

  async function run() {
    const c = cmd.trim()
    if (!c || busy) return
    setCmd('')
    histRef.current.unshift(c)
    histIdx.current = -1
    setBusy(true)
    setOut((o) => `${o}$ ${c}\n`)
    try {
      const r = await api.exec(sid, c)
      const text = r.blocked ? `⛔ ${r.output}` : (r.output || '(no output)')
      setOut((o) => `${o}${text}\n`)
    } catch (e) {
      setOut((o) => `${o}⚠ ${String(e)}\n`)
    } finally {
      setBusy(false)
      requestAnimationFrame(() => { if (outRef.current) outRef.current.scrollTop = outRef.current.scrollHeight })
    }
  }

  return (
    <div className="term">
      <div className="term-head">TERMINAL</div>
      <pre className="term-out" ref={outRef}>{out || '(gõ lệnh để chạy trong workspace — ví dụ: dir / ls)'} </pre>
      <div className="term-row">
        <span className="term-ps1">$</span>
        <input
          value={cmd}
          aria-label="Lệnh terminal"
          disabled={busy}
          placeholder={busy ? 'đang chạy…' : 'lệnh…'}
          onChange={(e) => setCmd(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); run() }
            else if (e.key === 'ArrowUp' && histRef.current.length) {
              histIdx.current = Math.min(histIdx.current + 1, histRef.current.length - 1)
              setCmd(histRef.current[histIdx.current])
            } else if (e.key === 'ArrowDown') {
              histIdx.current = Math.max(histIdx.current - 1, -1)
              setCmd(histIdx.current >= 0 ? histRef.current[histIdx.current] : '')
            }
          }}
        />
      </div>
    </div>
  )
}

export function FilesPane(props: {
  sid: string
  tree: FileNode[]
  selected: string | null
  content: string | null
  dirty: boolean
  onOpen: (p: string) => void
  onChange: (c: string) => void
  onSave: () => void
  onDelete: () => void
  onRefresh: () => void
  onNewFile: () => void
  onUpload: (fs: FileList | null) => void
  onExport: () => void
  onClose?: () => void
}) {
  const uploadRef = useRef<HTMLInputElement>(null)
  return (
    <aside className="files-pane" aria-label="Workspace">
      <div className="files-head">
        <span>WORKSPACE</span>
        <div className="files-actions">
          <button title="Tải file lên workspace" aria-label="Tải file lên workspace" onClick={() => uploadRef.current?.click()}>⬆</button>
          <input ref={uploadRef} type="file" multiple style={{ display: 'none' }} aria-label="Chọn file tải lên"
            onChange={(e) => { props.onUpload(e.target.files); e.currentTarget.value = '' }} />
          <button title="Xuất workspace (.zip)" aria-label="Xuất workspace" onClick={props.onExport}>⤓</button>
          <button title="File mới" aria-label="File mới" onClick={props.onNewFile}>＋</button>
          <button title="Làm mới" aria-label="Làm mới workspace" onClick={props.onRefresh}>⟳</button>
          {props.selected && <button title="Xóa file" aria-label="Xóa file" onClick={props.onDelete}>🗑</button>}
          <button className="files-close" title="Đóng panel Workspace" aria-label="Đóng panel Workspace" onClick={props.onClose}>✕</button>
        </div>
      </div>
      <div className="files-tree">
        {props.tree.length === 0
          ? <div className="empty">Workspace trống.<br />Nhờ agent tạo file nhé!</div>
          : props.tree.map((n) => (
            <TreeRow key={n.name} node={n} depth={0} path={n.name} selected={props.selected} onOpen={props.onOpen} />
          ))}
      </div>
      {props.selected !== null && (
        <div className="editor">
          <div className="editor-head">
            <code>{props.selected}</code>
            <button
              className={`btn-save ${props.dirty ? 'dirty' : ''}`}
              onClick={props.onSave}
              disabled={!props.dirty}
            >{props.dirty ? '● Lưu' : 'Đã lưu'}</button>
          </div>
          <textarea
            className="editor-area"
            aria-label={`Nội dung ${props.selected}`}
            spellCheck={false}
            value={props.content ?? ''}
            onChange={(e) => props.onChange(e.target.value)}
            placeholder="(file trống)"
          />
        </div>
      )}
      <Terminal sid={props.sid} />
    </aside>
  )
}
