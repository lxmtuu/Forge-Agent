import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { AuditEntry, ConnectorPreset, DoctorReport, KeyCheckResult, McpServerStatus, ModelInfo, Settings, SkillInfo, UsageTotals } from '../types'

const THEMES = [
  { id: 'dark', label: '🌑 Tối (mặc định)' },
  { id: 'light', label: '☀ Sáng' },
  { id: 'amber', label: '🌌 Amber CRT' },
] as const

const STATUS_STYLE: Record<string, string> = {
  ready: 'st-ok', starting: 'st-warn', stopped: 'st-dim', error: 'st-bad',
}

const TABS = [
  { id: 'conn', label: '📡 Kết nối' },
  { id: 'safe', label: '🛡 An toàn' },
  { id: 'mcp', label: '🔌 MCP' },
  { id: 'svc', label: '🔗 Dịch vụ' },
  { id: 'skl', label: '🧩 Skills' },
  { id: 'audit', label: '📘 Audit' },
  { id: 'sys', label: '🩺 Hệ thống' },
] as const
type TabId = typeof TABS[number]['id']

export function SettingsModal(props: {
  settings: Settings
  sid?: string | null
  onClose: () => void
  onSave: (apiKey?: string, model?: string, patch?: { approval_mode?: string; docker_sandbox?: boolean; max_tokens?: number; web_search?: boolean; allow_commands?: string[]; deny_commands?: string[]; custom_base_url?: string; auto_commit?: boolean; reasoning_effort?: string }) => Promise<void>
}) {
  const [tab, setTab] = useState<TabId>('conn')
  const [key, setKey] = useState('')
  const [model, setModel] = useState(props.settings.model)
  const [maxTokens, setMaxTokens] = useState(String(props.settings.max_tokens ?? 16384))
  const [approval, setApproval] = useState<string>(props.settings.approval_mode ?? 'guarded')
  const [docker, setDocker] = useState(props.settings.docker_sandbox)
  const [webSearch, setWebSearch] = useState(props.settings.web_search ?? false)
  const [allowCmds, setAllowCmds] = useState((props.settings.allow_commands ?? []).join('\n'))
  const [denyCmds, setDenyCmds] = useState((props.settings.deny_commands ?? []).join('\n'))
  const [baseUrl, setBaseUrl] = useState(props.settings.custom_base_url ?? '')
  const [effort, setEffort] = useState(props.settings.reasoning_effort ?? '')
  const [autoCommit, setAutoCommit] = useState(props.settings.auto_commit ?? false)
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)
  const [mcp, setMcp] = useState<McpServerStatus[]>([])
  const [mcpName, setMcpName] = useState('')
  const [mcpCmd, setMcpCmd] = useState('')
  const [mcpArgs, setMcpArgs] = useState('')
  const [mcpErr, setMcpErr] = useState<string | null>(null)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [modelFilter, setModelFilter] = useState('')
  const [totals, setTotals] = useState<UsageTotals | null>(null)
  const [keyCheck, setKeyCheck] = useState<KeyCheckResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [theme, setTheme] = useState(localStorage.getItem('forge-theme') || 'dark')
  const [doctorRep, setDoctorRep] = useState<DoctorReport | null>(null)
  const [doctoring, setDoctoring] = useState(false)

  // nền ban đầu — để phát hiện "có thay đổi chưa lưu"
  const initial = useMemo(() => ({
    model: props.settings.model,
    maxTokens: String(props.settings.max_tokens ?? 16384),
    approval: props.settings.approval_mode ?? 'guarded',
    docker: props.settings.docker_sandbox,
    webSearch: props.settings.web_search ?? false,
    allowCmds: (props.settings.allow_commands ?? []).join('\n'),
    denyCmds: (props.settings.deny_commands ?? []).join('\n'),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [])

  const dirty =
    key.trim() !== '' ||
    model !== initial.model ||
    maxTokens !== initial.maxTokens ||
    approval !== initial.approval ||
    docker !== initial.docker ||
    webSearch !== initial.webSearch ||
    allowCmds !== initial.allowCmds ||
    denyCmds !== initial.denyCmds ||
    baseUrl !== (props.settings.custom_base_url ?? '') ||
    effort !== (props.settings.reasoning_effort ?? '') ||
    autoCommit !== (props.settings.auto_commit ?? false)

  const applyTheme = (t: string) => {
    setTheme(t)
    localStorage.setItem('forge-theme', t)
    document.documentElement.dataset.theme = t === 'dark' ? '' : t
  }

  const doKeyCheck = (k?: string) => {
    setChecking(true)
    api.keyCheck(k).then(setKeyCheck).catch((e) => setKeyCheck({ valid: false, error: String(e) }))
      .finally(() => setChecking(false))
  }

  const reloadMcp = () => api.mcpStatus().then(setMcp).catch(() => {})

  // ── Connectors OAuth (tab Dịch vụ) ──
  const [svcPresets, setSvcPresets] = useState<ConnectorPreset[] | null>(null)
  const [svcCreds, setSvcCreds] = useState<Record<string, { cid: string; csec: string }>>({})
  const [svcBusy, setSvcBusy] = useState<string | null>(null)

  const loadSvc = () => api.connectorPresets().then(setSvcPresets).catch(() => setSvcPresets([]))

  // ── Skills tab ──
  const [skillRows, setSkillRows] = useState<SkillInfo[] | null>(null)
  const [skillDiags, setSkillDiags] = useState<string[]>([])
  const [skillErr, setSkillErr] = useState<string | null>(null)
  const [skillBusy, setSkillBusy] = useState<string | null>(null)

  const loadSkills = () => {
    if (!props.sid) { setSkillErr('Mở một phiên để xem skills của workspace đó.'); return }
    setSkillErr(null)
    api.skills(props.sid).then((d) => { setSkillRows(d.skills); setSkillDiags(d.diags) })
      .catch((e) => setSkillErr(String((e as Error).message ?? e)))
  }

  // ── Audit log tab ──
  const [auditRows, setAuditRows] = useState<AuditEntry[] | null>(null)
  const [auditFilter, setAuditFilter] = useState('')
  const loadAudit = () => api.audit(200).then((rows) => setAuditRows(rows)).catch(() => setAuditRows([]))
  useEffect(() => {
    if (tab === 'audit' && auditRows === null) loadAudit()
    if (tab === 'svc' && svcPresets === null) loadSvc()
    if (tab === 'skl') loadSkills()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  const svcConnect = async (id: string) => {
    setSvcBusy(id)
    const creds = svcCreds[id]
    try {
      await api.oauthStart(id, creds?.cid || undefined, creds?.csec || undefined)
      let done = false
      for (let i = 0; i < 60 && !done; i++) {
        await new Promise((r) => setTimeout(r, 2000))
        try {
          const st = await api.oauthStatus(id)
          if (st.status === 'connected' || st.status === 'error') done = true
        } catch { /* server restart… */ }
      }
    } catch { /* ignore */ }
    await loadSvc()
    setSvcBusy(null)
  }

  useEffect(() => {
    reloadMcp()
    api.models().then((d) => setModels(d.models)).catch(() => {})
    api.usage().then(setTotals).catch(() => {})
  }, [])

  const tryClose = () => {
    if (dirty && !confirm('Có thay đổi CHƯA LƯU — vẫn đóng?')) return
    props.onClose()
  }

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') tryClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty])

  async function doSave() {
    setSaving(true); setSaveErr(null)
    try {
      const mt = parseInt(maxTokens, 10)
      await props.onSave(key || undefined, model || undefined, {
        approval_mode: approval,
        docker_sandbox: docker,
        web_search: webSearch,
        allow_commands: allowCmds.split('\n').map((s) => s.trim()).filter(Boolean),
        deny_commands: denyCmds.split('\n').map((s) => s.trim()).filter(Boolean),
        custom_base_url: baseUrl.trim(),
        reasoning_effort: effort,
        auto_commit: autoCommit,
        ...(Number.isFinite(mt) && mt >= 256 && mt <= 65536 ? { max_tokens: mt } : {}),
      })
      props.onClose()
    } catch (e) {
      setSaveErr(`Không lưu được: ${(e as Error).message ?? e}`)
    } finally { setSaving(false) }
  }

  const filteredModels = modelFilter
    ? (modelFilter.trim().toLowerCase() === 'free'
        ? models.filter((m) => m.free)
        : models.filter((m) => m.id.toLowerCase().includes(modelFilter.toLowerCase()))
      ).slice(0, 40)
    : models.slice(0, 40)

  return (
    <div className="modal-backdrop" onClick={tryClose}>
      <div className="modal modal-wide" role="dialog" aria-modal="true" aria-label="Cài đặt" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>⚙ Cài đặt{dirty && <span className="dirty-dot" title="Có thay đổi chưa lưu" />}</h3>
          <button className="btn-ghost btn-sm" title="Đóng (Esc)" onClick={tryClose}>✕</button>
        </div>

        {totals && (
          <div className="usage-line">
            📊 Toàn bộ hệ thống: <b>{totals.sessions}</b> phiên ·{' '}
            <b>{(totals.total_tokens ?? 0).toLocaleString('vi-VN')}</b> tokens
            (↑{totals.prompt_tokens} ↓{totals.completion_tokens})
            {totals.cost > 0 && <> · ~${totals.cost.toFixed(4)}</>}
          </div>
        )}

        <div className="settings-tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id}
              className={`settings-tab ${tab === t.id ? 'on' : ''}`}
              onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </div>

        <div className="settings-body">
        {tab === 'conn' && (
          <>
            <div className="field">
              <span>Base URL tuỳ chỉnh <em>(model cục bộ — Ollama/LM Studio/vLLM; để trống = OpenRouter)</em></span>
              <input
                placeholder="vd: http://localhost:11434/v1"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
              <small>Dán URL rồi đặt Model thành tên cục bộ (vd <code>llama3.2</code>, <code>qwen2.5-coder</code>). API key tuỳ chọn — điền ở ô key bên trên nếu server cần.</small>
            </div>
            <div className="field">
              <span>Effort suy luận <em>(reasoning budget — chỉ áp dụng qua OpenRouter)</em></span>
              <select value={effort} onChange={(e) => setEffort(e.target.value)}>
                <option value="">Mặc định của model</option>
                <option value="low">Low — nhanh, rẻ</option>
                <option value="medium">Medium — cân bằng</option>
                <option value="high">High — suy luận sâu, chậm hơn</option>
              </select>
            </div>
            <label className="field">
              <span>OpenRouter API Key {props.settings.key_masked && <em>(hiện tại: {props.settings.key_masked})</em>}</span>
              <div className="key-row">
                <input type="password" placeholder="sk-or-v1-..." value={key}
                  onChange={(e) => { setKey(e.target.value); setKeyCheck(null) }} />
                <button className="btn-ghost btn-sm" disabled={checking}
                  onClick={() => doKeyCheck(key || undefined)}>
                  {checking ? 'Đang kiểm tra…' : key.trim() ? '🔍 Kiểm tra key mới' : '🔍 Kiểm tra key đã lưu'}
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
                  <button key={m.id} className={`model-chip ${m.free ? 'free-chip' : ''}`}
                    title={`${m.name} · context ${m.context ?? '?'} · ${m.free ? 'MIỄN PHÍ' : `$${(m.prompt_price * 1e6).toFixed(2)}/M in · $${(m.completion_price * 1e6).toFixed(2)}/M out`}`}
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
          </>
        )}

        {tab === 'safe' && (
          <>
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

            <label className="field check">
              <input type="checkbox" checked={autoCommit} onChange={(e) => setAutoCommit(e.target.checked)} />
              <span>📦 Auto-commit mỗi lượt <em>— git init workspace (nếu chưa có) và commit thay đổi với message Conventional Commits do model rẻ sinh (theo pattern Aider). Xem <code>git log</code> trong workspace.</em></span>
            </label>

            <label className="field check">
              <input type="checkbox" checked={webSearch} onChange={(e) => setWebSearch(e.target.checked)} />
              <span>🌐 Web search qua OpenRouter <code>:online</code> <em>— mọi lượt chat sẽ tìm web (tốn ~$0.005/lượt)</em></span>
            </label>

            <div className="field">
              <span>Permission patterns <em>(glob, mỗi dòng 1 mẫu — vd <code>git *</code>, <code>npm run *</code>)</em></span>
              <div className="perm-grid">
                <div className="perm-col">
                  <small className="perm-label" style={{ color: 'var(--green)' }}>✓ Allow (nâng warn → được chạy)</small>
                  <textarea className="perm-area" value={allowCmds} onChange={(e) => setAllowCmds(e.target.value)} rows={4}
                    placeholder={'git status\nnpm run *\npytest *'} />
                </div>
                <div className="perm-col">
                  <small className="perm-label" style={{ color: 'var(--red)' }}>✕ Deny (chặn tuyệt đối)</small>
                  <textarea className="perm-area" value={denyCmds} onChange={(e) => setDenyCmds(e.target.value)} rows={4}
                    placeholder={'git push *\nrm -rf *\ncurl * | sh'} />
                </div>
              </div>
            </div>
          </>
        )}

        {tab === 'mcp' && (
          <>
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
                    setMcpErr(null)
                    try {
                      const args = mcpArgs.split(',').map((x) => x.trim()).filter(Boolean)
                      const list = await api.mcpAdd(mcpName.trim(), mcpCmd.trim(), args)
                      setMcp(list); setMcpName(''); setMcpCmd(''); setMcpArgs('')
                    } catch (e) {
                      setMcpErr(`Không thêm được server: ${(e as Error).message ?? e}`)
                    }
                  }}
                >＋ Thêm</button>
              </div>
              {mcpErr && <div className="save-error">{mcpErr}</div>}
              <small>VD: filesystem server — <code>npx</code> + <code>-y, @modelcontextprotocol/server-filesystem, /tmp/du-lieu</code>. Agent sẽ nhận thêm tool <code>mcp_fs_*</code> tự động.</small>
            </div>
          </>
        )}

        {tab === 'svc' && (
          <>
            <div className="field">
              <span>Dịch vụ & connectors <em>(OAuth 2.1 — đăng nhập trong trình duyệt, token lưu secrets.json chmod 600)</em></span>
              <div className="svc-list">
                {!svcPresets && <div className="empty" style={{ padding: 10 }}>Đang nạp…</div>}
                {svcPresets && svcPresets.map((p) => (
                  <div key={p.id} className="svc-row">
                    <div className="svc-head">
                      <b>{p.label.split(' — ')[0]}</b>
                      {p.connected ? <span className="st st-ok">đã kết nối {p.masked ? `· ${p.masked}` : ''}</span>
                        : <span className={`st ${p.installed ? 'st-warn' : 'st-dim'}`}>{p.installed ? 'chưa đăng nhập' : 'chưa cài'}</span>}
                      {!p.installed ? (
                        <button className="btn-primary btn-sm" onClick={() => api.connectorInstall(p.id).then(loadSvc).catch(() => {})}>＋ Cài</button>
                      ) : (
                        <button className="btn-ghost btn-sm" onClick={() => confirm(`Gỡ '${p.label.split(' — ')[0]}'?`) && api.connectorRemove(p.id).then(loadSvc).catch(() => {})}>🗑 Gỡ</button>
                      )}
                      {p.oauth && p.connected && (
                        <button className="btn-ghost btn-sm" onClick={() => api.oauthDisconnect(p.id).then(loadSvc)}>Đăng xuất</button>
                      )}
                    </div>
                    {p.oauth && (
                      <div className="svc-oauth">
                        {!p.connected && (
                          <>
                            <input placeholder="client_id" value={svcCreds[p.id]?.cid ?? ''}
                              onChange={(e) => setSvcCreds({ ...svcCreds, [p.id]: { cid: e.target.value, csec: svcCreds[p.id]?.csec ?? '' } })} />
                            <input placeholder="client_secret (nếu có)" type="password" value={svcCreds[p.id]?.csec ?? ''}
                              onChange={(e) => setSvcCreds({ ...svcCreds, [p.id]: { cid: svcCreds[p.id]?.cid ?? '', csec: e.target.value } })} />
                            <button className="btn-primary btn-sm" disabled={svcBusy === p.id}
                              onClick={() => { void svcConnect(p.id) }}>
                              {svcBusy === p.id ? '⏳ Chờ duyệt trong trình duyệt…' : '🔗 Kết nối (OAuth)'}
                            </button>
                          </>
                        )}
                        <small>{p.auth_hint}</small>
                      </div>
                    )}
                    {!p.oauth && <small>{p.auth_hint}</small>}
                  </div>
                ))}
              </div>
              <small>Flow chuẩn OAuth 2.1: PKCE S256 + loopback 127.0.0.1:8765/callback + state chống CSRF. Preset chưa OAuth: cài qua <code>/connectors add</code>.</small>
            </div>
          </>
        )}
        {tab === 'skl' && (
          <>
            <div className="field">
              <span>Skills <em>(chuẩn SKILL.md — quét .forge/skills · .agents/skills · .claude/skills · ~/.forge/skills)</em></span>
              {skillErr && <div className="save-error">{skillErr}</div>}
              {!skillErr && (
                <div className="skill-list">
                  {!skillRows && <div className="empty" style={{ padding: 10 }}>Đang nạp…</div>}
                  {skillRows && skillRows.length === 0 && (
                    <div className="empty" style={{ padding: 10 }}>Chưa có skill nào — <code>/skills new &lt;tên&gt;</code> để tạo.</div>
                  )}
                  {skillRows && skillRows.map((k) => (
                    <div key={k.path} className={`skill-row ${k.trusted ? '' : 'untrusted'}`}>
                      <div className="skill-head">
                        <b>{k.name}</b>
                        {k.fmt === 'standard' ? <span className="st st-dim">standard</span> : <span className="st st-dim">legacy</span>}
                        {!k.trusted && <span className="st st-warn">🔒 chưa tin</span>}
                        {!k.model_invocable && <span className="st st-dim">🔕 chỉ gọi tay</span>}
                      </div>
                      <div className="skill-desc">{k.description.slice(0, 140)}{k.description.length > 140 ? '…' : ''}</div>
                      {k.allowed_tools && <div className="skill-meta">🔑 {k.allowed_tools}</div>}
                      {k.diags.length > 0 && <div className="skill-meta">⚠ {k.diags.join('; ')}</div>}
                      <div className="skill-actions">
                        <button className="btn-ghost btn-sm" disabled={skillBusy === k.path}
                          onClick={() => { setSkillBusy(k.path)
                            api.skillToggle(props.sid as string, k.path, !k.model_invocable)
                              .then(() => api.skills(props.sid as string)).then((d) => { setSkillRows(d.skills); setSkillDiags(d.diags) })
                              .catch(() => {}).finally(() => setSkillBusy(null)) }}>
                          {skillBusy === k.path ? '…' : k.model_invocable ? '🔕 Cấm model gọi' : '✅ Cho model gọi'}
                        </button>
                        {!k.trusted && k.source === 'project' && (
                          <button className="btn-primary btn-sm" disabled={skillBusy === k.path}
                            onClick={() => { setSkillBusy(k.path)
                              api.skillTrust(props.sid as string, k.name)
                                .then(() => api.skills(props.sid as string)).then((d) => { setSkillRows(d.skills); setSkillDiags(d.diags) })
                                .catch(() => {}).finally(() => setSkillBusy(null)) }}>
                            🔓 Tin skill này
                          </button>
                        )}
                      </div>
                      <code className="skill-path">{k.path}</code>
                    </div>
                  ))}
                </div>
              )}
              {skillDiags.length > 0 && (
                <small>⚠ {skillDiags.length} cảnh báo diagnostics: {skillDiags.slice(0, 3).join(' · ')}</small>
              )}
              <small>Bật/tắt chỉ đổi frontmatter <code>disable-model-invocation</code> trong SKILL.md — hiệu lực ngay.</small>
            </div>
          </>
        )}
        {tab === 'audit' && (
          <>
            <div className="field">
              <span>Audit log <em>(mọi tool call của agent — token tự mask, file data/audit/)</em></span>
              <div className="audit-bar">
                <input
                  placeholder="Lọc theo tool/nguồn/đối số…"
                  value={auditFilter}
                  onChange={(e) => setAuditFilter(e.target.value)}
                />
                <button className="btn-ghost btn-sm" onClick={() => { setAuditRows(null); loadAudit() }}>⟳ Nạp lại</button>
                <a className="btn-ghost btn-sm" href="/api/audit/export" download title="Tải tối đa 2000 mục mới nhất (CSV)">⤓ Xuất CSV</a>
              </div>
              <div className="audit-list">
                {!auditRows && <div className="empty" style={{ padding: 10 }}>Đang nạp…</div>}
                {auditRows && auditRows.length === 0 && (
                  <div className="empty" style={{ padding: 10 }}>Chưa có tool call nào — cho agent chạy một lượt rồi quay lại.</div>
                )}
                {auditRows && auditRows
                  .filter((e) => {
                    if (!auditFilter.trim()) return true
                    const q = auditFilter.toLowerCase()
                    return (e.tool + ' ' + e.source + ' ' + JSON.stringify(e.args ?? {}) + ' ' + (e.note ?? '')).toLowerCase().includes(q)
                  })
                  .map((e, i) => (
                    <div key={i} className={`audit-row ${e.ok ? '' : 'bad'}`}>
                      <span className="audit-ts">{String(e.ts).slice(11, 19)}</span>
                      <span className="audit-ok">{e.ok ? '✅' : '❌'}</span>
                      <b className="audit-tool">{e.tool}</b>
                      <span className="audit-src">{e.source}</span>
                      <span className="audit-ms">{e.ms != null ? `${e.ms}ms` : '—'}</span>
                      <span className="audit-args" title={JSON.stringify(e.args ?? {})}>
                        {Object.entries(e.args ?? {}).map(([k, v]) => `${k}=${v}`).join(' ').slice(0, 90)}
                        {e.note ? ` · ${e.note}` : ''}
                      </span>
                    </div>
                  ))}
              </div>
              <small>Hiển thị tối đa 200 mục mới nhất. Xem đầy đủ: <code>/audit</code> hoặc <code>data/audit/&lt;ngày&gt;.jsonl</code></small>
            </div>
          </>
        )}
        {tab === 'sys' && (
          <>
            <div className="field">
              <span>Giao diện <em>(theme lưu trên máy bạn, áp dụng ngay)</em></span>
              <select className="sel" value={theme} onChange={(e) => applyTheme(e.target.value)}>
                {THEMES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
            </div>

            <div className="field">
              <span>Chẩn đoán hệ thống <em>(kiểm tra Python, git, key, model, LSP, MCP…)</em></span>
              <button className="btn-ghost" disabled={doctoring}
                onClick={async () => {
                  setDoctoring(true)
                  try { setDoctorRep(await api.doctor()) } catch { /* ignore */ }
                  finally { setDoctoring(false) }
                }}>
                {doctoring ? 'Đang chẩn đoán…' : '🩺 Chạy chẩn đoán'}
              </button>
              {doctorRep && (
                <div className="doctor-list">
                  {doctorRep.checks.map((c, i) => (
                    <div key={i} className={`doctor-row ${c.ok ? '' : 'bad'}`}>
                      {c.ok ? '✓' : '✗'} <b>{c.name}</b> — <span className="doctor-detail">{c.detail}</span>
                    </div>
                  ))}
                  <div className="doctor-summary">{doctorRep.summary}</div>
                </div>
              )}
            </div>

            <div className="field">
              <span>Bảo mật & dữ liệu</span>
              <small style={{ lineHeight: 1.7 }}>
                🔐 Key lưu trong <code>data/config.json</code> trên server của bạn (chmod 600), chỉ gọi thẳng OpenRouter — không qua trung gian.<br />
                🛡 Guarded mode chặn lệnh nguy hiểm (<code>sudo</code>, <code>rm -rf /</code>, pipe-từ-mạng…).<br />
                💾 Checkpoint: mọi thay đổi file của agent đều có bản git nội bộ — nút ↩ Undo hoàn tác được.
              </small>
            </div>
          </>
        )}
        </div>

        {saveErr && <div className="save-error">{saveErr}</div>}

        <div className="modal-actions" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <button className="btn-ghost btn-sm" onClick={tryClose}>Đóng</button>
          <button
            className="btn-primary"
            disabled={saving || !dirty}
            title={dirty ? 'Áp dụng các thay đổi' : 'Chưa có thay đổi nào'}
            onClick={doSave}
          >{saving ? 'Đang lưu…' : dirty ? '💾 Lưu thay đổi' : 'Lưu cài đặt'}</button>
        </div>
      </div>
    </div>
  )
}
