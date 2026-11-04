import React, { useEffect, useState } from 'react'
import { api } from '../api'
import type { McpServerStatus, Settings } from '../types'

const STATUS_STYLE: Record<string, string> = {
  ready: 'st-ok', starting: 'st-warn', stopped: 'st-dim', error: 'st-bad',
}

export function SettingsModal(props: {
  settings: Settings
  onClose: () => void
  onSave: (apiKey?: string, model?: string, patch?: { approval_mode?: string; docker_sandbox?: boolean }) => Promise<void>
}) {
  const [key, setKey] = useState('')
  const [model, setModel] = useState(props.settings.model)
  const [approval, setApproval] = useState<string>(props.settings.approval_mode ?? 'guarded')
  const [docker, setDocker] = useState(props.settings.docker_sandbox)
  const [saving, setSaving] = useState(false)
  const [mcp, setMcp] = useState<McpServerStatus[]>([])
  const [mcpName, setMcpName] = useState('')
  const [mcpCmd, setMcpCmd] = useState('')
  const [mcpArgs, setMcpArgs] = useState('')

  const reloadMcp = () => api.mcpStatus().then(setMcp).catch(() => {})
  useEffect(() => { reloadMcp() }, [])

  return (
    <div className="modal-backdrop" onClick={props.onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>⚙ Cài đặt</h3>
          <button className="btn-ghost btn-sm" onClick={props.onClose}>✕</button>
        </div>

        <label className="field">
          <span>OpenRouter API Key {props.settings.key_masked && <em>(hiện tại: {props.settings.key_masked})</em>}</span>
          <input type="password" placeholder="sk-or-v1-..." value={key} onChange={(e) => setKey(e.target.value)} />
          <small>Lấy key tại <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">openrouter.ai/keys</a> — để trống nếu không đổi.</small>
        </label>

        <label className="field">
          <span>Model</span>
          <input list="models" value={model} onChange={(e) => setModel(e.target.value)} />
          <datalist id="models">
            {props.settings.default_models.map((m) => <option key={m} value={m} />)}
          </datalist>
        </label>

        <div className="field">
          <span>Chế độ duyệt lệnh shell</span>
          <div className="seg">
            <button className={`seg-btn ${approval === 'guarded' ? 'on' : ''}`}
              onClick={() => setApproval('guarded')}>
              🛡 Guarded<span className="seg-desc">chặn lệnh nguy hiểm</span>
            </button>
            <button className={`seg-btn ${approval === 'auto' ? 'on' : ''}`}
              onClick={() => setApproval('auto')}>
              ⚡ Auto (YOLO)<span className="seg-desc">chạy mọi lệnh — rủi ro tự chịu</span>
            </button>
          </div>
        </div>

        {props.settings.docker_available && (
          <label className="field check">
            <input type="checkbox" checked={docker} onChange={(e) => setDocker(e.target.checked)} />
            <span>🐳 Chạy lệnh trong Docker sandbox (không mạng, giới hạn CPU/RAM)</span>
          </label>
        )}

        <div className="field">
          <span>MCP servers <em>(Model Context Protocol — nối tool bên ngoài vào agent)</em></span>
          <div className="mcp-list">
            {mcp.length === 0 && <div className="empty" style={{ padding: 10 }}>Chưa có server nào.</div>}
            {mcp.map((s) => (
              <div key={s.name} className="mcp-item">
                <span className={`st ${STATUS_STYLE[s.status] ?? 'st-dim'}`}>{s.status}</span>
                <div className="mcp-info">
                  <b>{s.name}</b> <code>{s.command} {s.args.join(' ')}</code>
                  <div className="mcp-tools">{s.tools.length ? s.tools.join(', ') : (s.error ?? '—')}</div>
                </div>
                <div className="mcp-actions">
                  <button title="Khởi động lại" onClick={() => api.mcpRefresh(s.name).then(setMcp)}>⟳</button>
                  <button title="Gỡ" onClick={() => confirm(`Gỡ ${s.name}?`) && api.mcpRemove(s.name).then(setMcp)}>🗑</button>
                </div>
              </div>
            ))}
          </div>
          <div className="mcp-add">
            <input placeholder="tên (vd: fs)" value={mcpName} onChange={(e) => setMcpName(e.target.value)} />
            <input placeholder="lệnh (vd: npx)" value={mcpCmd} onChange={(e) => setMcpCmd(e.target.value)} />
            <input placeholder="tham số, cách nhau bởi dấu phẩy" value={mcpArgs} onChange={(e) => setMcpArgs(e.target.value)} />
            <button
              className="btn-primary btn-sm"
              disabled={!mcpName.trim() || !mcpCmd.trim()}
              onClick={async () => {
                const args = mcpArgs.split(',').map((x) => x.trim()).filter(Boolean)
                const list = await api.mcpAdd(mcpName.trim(), mcpCmd.trim(), args)
                setMcp(list); setMcpName(''); setMcpCmd(''); setMcpArgs('')
              }}
            >＋ Thêm</button>
          </div>
          <small>VD: filesystem server — <code>npx</code> + <code>-y, @modelcontextprotocol/server-filesystem, /tmp/du-lieu</code>. Agent sẽ nhận thêm tool <code>mcp_fs_*</code> tự động.</small>
        </div>

        <div className="modal-actions">
          <button
            className="btn-primary"
            disabled={saving}
            onClick={async () => {
              setSaving(true)
              try {
                await props.onSave(key || undefined, model || undefined,
                  { approval_mode: approval, docker_sandbox: docker })
                props.onClose()
              } finally { setSaving(false) }
            }}
          >{saving ? 'Đang lưu…' : 'Lưu cài đặt'}</button>
        </div>

        <p className="modal-note">
          🔐 Key lưu trong <code>data/config.json</code> trên server của bạn (chmod 600), chỉ gọi thẳng OpenRouter.
          Guarded mode chặn lệnh nguy hiểm (<code>sudo</code>, <code>rm -rf /</code>, pipe-from-net…).
        </p>
      </div>
    </div>
  )
}
