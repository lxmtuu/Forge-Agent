import React, { useEffect, useState } from 'react'
import { api } from '../api'
import type { KeyCheckResult, McpServerStatus, ModelInfo, Settings, UsageTotals } from '../types'

const STATUS_STYLE: Record<string, string> = {
  ready: 'st-ok', starting: 'st-warn', stopped: 'st-dim', error: 'st-bad',
}

export function SettingsModal(props: {
  settings: Settings
  onClose: () => void
  onSave: (apiKey?: string, model?: string, patch?: { approval_mode?: string; docker_sandbox?: boolean; max_tokens?: number }) => Promise<void>
}) {
  const [key, setKey] = useState('')
  const [model, setModel] = useState(props.settings.model)
  const [maxTokens, setMaxTokens] = useState(String(props.settings.max_tokens ?? 16384))
  const [approval, setApproval] = useState<string>(props.settings.approval_mode ?? 'guarded')
  const [docker, setDocker] = useState(props.settings.docker_sandbox)
  const [saving, setSaving] = useState(false)
  const [mcp, setMcp] = useState<McpServerStatus[]>([])
  const [mcpName, setMcpName] = useState('')
  const [mcpCmd, setMcpCmd] = useState('')
  const [mcpArgs, setMcpArgs] = useState('')
  const [models, setModels] = useState<ModelInfo[]>([])
  const [modelFilter, setModelFilter] = useState('')
  const [totals, setTotals] = useState<UsageTotals | null>(null)
  const [keyCheck, setKeyCheck] = useState<KeyCheckResult | null>(null)
  const [checking, setChecking] = useState(false)

  const doKeyCheck = (k?: string) => {
    setChecking(true)
    api.keyCheck(k).then(setKeyCheck).catch((e) => setKeyCheck({ valid: false, error: String(e) }))
      .finally(() => setChecking(false))
  }

  const reloadMcp = () => api.mcpStatus().then(setMcp).catch(() => {})
  useEffect(() => {
    reloadMcp()
    api.models().then((d) => setModels(d.models)).catch(() => {})
    api.usage().then(setTotals).catch(() => {})
  }, [])

  const filteredModels = modelFilter
    ? (modelFilter.trim().toLowerCase() === 'free'
        ? models.filter((m) => m.free)
        : models.filter((m) => m.id.toLowerCase().includes(modelFilter.toLowerCase()))
      ).slice(0, 40)
    : models.slice(0, 40)

  return (
    <div className="modal-backdrop" onClick={props.onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>⚙ Cài đặt</h3>
          <button className="btn-ghost btn-sm" onClick={props.onClose}>✕</button>
        </div>

        {totals && (
          <div className="usage-line">
            📊 Toàn bộ hệ thống: <b>{totals.sessions}</b> phiên ·{' '}
            <b>{(totals.total_tokens ?? 0).toLocaleString('vi-VN')}</b> tokens
            (↑{totals.prompt_tokens} ↓{totals.completion_tokens})
            {totals.cost > 0 && <> · ~${totals.cost.toFixed(4)}</>}
          </div>
        )}

        <label className="field">
          <span>OpenRouter API Key {props.settings.key_masked && <em>(hiện tại: {props.settings.key_masked})</em>}</span>
          <div className="key-row">
            <input type="password" placeholder="sk-or-v1-..." value={key} onChange={(e) => { setKey(e.target.value); setKeyCheck(null) }} />
            <button className="btn-ghost btn-sm" disabled={checking} onClick={() => doKeyCheck(key || undefined)}>
              {checking ? 'Đang kiểm tra…' : '🔍 Kiểm tra'}
            </button>
          </div>
          <small>Lấy key tại <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">openrouter.ai/keys</a> — dùng nút Copy trên trang đó, để trống nếu không đổi.</small>
          {keyCheck && (keyCheck.valid ? (
            <div className="key-result ok">
              ✅ Key hợp lệ — «{keyCheck.label}» · đã dùng ${keyCheck.usage ?? 0}
              {keyCheck.limit != null ? ` / hạn mức $${keyCheck.limit}` : ' · không giới hạn'}
              {keyCheck.is_free_tier && ' · free tier'}
            </div>
          ) : (
            <div className="key-result bad">
              ❌ {keyCheck.error}
              {keyCheck.hint && <div className="key-hint">💡 {keyCheck.hint}</div>}
            </div>
          ))}
        </label>

        <div className="field">
          <span>Model <em>({models.length > 0 ? `${models.length} model đồng bộ từ OpenRouter` : 'đang đồng bộ…'})</em></span>
          <input list="models" value={model} onChange={(e) => setModel(e.target.value)} />
          <datalist id="models">
            {(models.length ? models.map((m) => m.id) : props.settings.default_models).map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          <div className="filter-presets">
            <button className={`preset ${modelFilter === 'free' ? 'on' : ''}`} onClick={() => setModelFilter(modelFilter === 'free' ? '' : 'free')}>🆓 Miễn phí</button>
            <button className={`preset ${modelFilter === 'claude' ? 'on' : ''}`} onClick={() => setModelFilter('claude')}>Claude</button>
            <button className={`preset ${modelFilter === 'gpt' ? 'on' : ''}`} onClick={() => setModelFilter('gpt')}>GPT</button>
            <button className={`preset ${modelFilter === 'coder' ? 'on' : ''}`} onClick={() => setModelFilter('coder')}>Coder</button>
          </div>
          <input
            className="model-filter"
            placeholder="Lọc danh sách model… (gõ 'free' để xem model miễn phí)"
            value={modelFilter}
            onChange={(e) => setModelFilter(e.target.value)}
          />
          <div className="model-suggest">
            {filteredModels.map((m) => (
              <button key={m.id} className={`model-chip ${m.free ? 'free-chip' : ''}`} title={`${m.name} · context ${m.context ?? '?'} · ${m.free ? 'MIỄN PHÍ' : `$${(m.prompt_price * 1e6).toFixed(2)}/M in · $${(m.completion_price * 1e6).toFixed(2)}/M out`}`}
                onClick={() => { setModel(m.id); setModelFilter('') }}>
                {m.free ? '🆓 ' : ''}{m.id}
              </button>
            ))}
          </div>
          <small>💡 Tài khoản chưa nạp credit → dùng model 🆓 (vd <code>openrouter/free</code>). Model trả phí (Claude/GPT) cần credit tại openrouter.ai/credits.</small>
        </div>

        <label className="field">
          <span>Max tokens mỗi lượt phản hồi <em>(thấp hơn = tốn ít credit đặt cọc hơn)</em></span>
          <input
            type="number"
            min={256}
            max={65536}
            step={256}
            value={maxTokens}
            onChange={(e) => setMaxTokens(e.target.value)}
          />
          <small>Mặc định 16384. Nếu bị lỗi 402 với model trả phí, thử giảm xuống 4096.</small>
        </label>

        <div className="field">
          <span>Chế độ duyệt lệnh shell</span>
          <div className="seg seg-3">
            <button className={`seg-btn ${approval === 'guarded' ? 'on' : ''}`}
              onClick={() => setApproval('guarded')}>
              🛡 Guarded<span className="seg-desc">chặn lệnh nguy hiểm</span>
            </button>
            <button className={`seg-btn ${approval === 'ask' ? 'on' : ''}`}
              onClick={() => setApproval('ask')}>
              🔔 Hỏi từng lệnh<span className="seg-desc">popup phê duyệt warn/danger</span>
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
                const mt = parseInt(maxTokens, 10)
                await props.onSave(key || undefined, model || undefined, {
                  approval_mode: approval,
                  docker_sandbox: docker,
                  ...(Number.isFinite(mt) && mt >= 256 && mt <= 65536 ? { max_tokens: mt } : {}),
                })
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
