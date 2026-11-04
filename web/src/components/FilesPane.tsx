import React, { useState } from 'react'
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
        <div className="tree-row dir" style={{ paddingLeft: 8 + depth * 14 }} onClick={() => setOpen(!open)}>
          <span className="chev-sm">{open ? '▾' : '▸'}</span> 📁 {node.name}
        </div>
        {open && (node.children ?? []).map((c) => (
          <TreeRow key={c.name + (c.path ?? '')} node={c} depth={depth + 1}
            path={path ? `${path}/${c.name}` : c.name} selected={selected} onOpen={onOpen} />
        ))}
      </div>
    )
  }
  const full = path
  return (
    <div className={`tree-row file ${selected === full ? 'active' : ''}`}
      style={{ paddingLeft: 8 + depth * 14 + 14 }} onClick={() => onOpen(full)}>
      📄 {node.name}
    </div>
  )
}

export function FilesPane(props: {
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
}) {
  return (
    <div className="files-pane">
      <div className="files-head">
        <span>FILES</span>
        <div className="files-actions">
          <label title="Tải file lên workspace" className="upload-label">
            ⬆
            <input type="file" multiple style={{ display: 'none' }}
              onChange={(e) => { props.onUpload(e.target.files); e.currentTarget.value = '' }} />
          </label>
          <button title="Xuất workspace (.zip)" onClick={props.onExport}>⤓</button>
          <button title="File mới" onClick={props.onNewFile}>＋</button>
          <button title="Làm mới" onClick={props.onRefresh}>⟳</button>
          {props.selected && <button title="Xóa file" onClick={props.onDelete}>🗑</button>}
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
            spellCheck={false}
            value={props.content ?? ''}
            onChange={(e) => props.onChange(e.target.value)}
            placeholder="(file trống)"
          />
        </div>
      )}
    </div>
  )
}
