import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { AuthUser, GoogleAuthConfig } from '../api'
import type { AuditEntry, ConnectorPreset, DoctorReport, KeyCheckResult, McpServerStatus, ModelInfo, Settings, SkillInfo, UsageTotals } from '../types'
import { useI18n } from '../i18n'

const THEMES = [
  { id: 'dark', label: ['🌑 Tối (mặc định)', '🌑 Dark (default)'] },
  { id: 'light', label: ['☀ Sáng', '☀ Light'] },
  { id: 'amber', label: ['🌌 Amber CRT', '🌌 Amber CRT'] },
] as const

const STATUS_STYLE: Record<string, string> = {
  ready: 'st-ok', starting: 'st-warn', stopped: 'st-dim', error: 'st-bad',
}

const TABS = [
  { id: 'conn', label: ['📡 Kết nối', '📡 Connection'] },
  { id: 'ui', label: ['🎨 Giao diện', '🎨 Appearance'] },
  { id: 'team', label: ['👥 Team', '👥 Team'] },
  { id: 'safe', label: ['🛡 An toàn', '🛡 Security'] },
  { id: 'mcp', label: ['🔌 MCP', '🔌 MCP'] },
  { id: 'svc', label: ['🔗 Dịch vụ', '🔗 Connectors'] },
  { id: 'skl', label: ['🧩 Skills', '🧩 Skills'] },
  { id: 'audit', label: ['📘 Audit', '📘 Audit'] },
  { id: 'sys', label: ['🩺 Hệ thống', '🩺 System'] },
] as const
type TabId = typeof TABS[number]['id']

export function SettingsModal(props: {
  settings: Settings
  sid?: string | null
  onClose: () => void
  onSave: (apiKey?: string, model?: string, patch?: { approval_mode?: string; docker_sandbox?: boolean; max_tokens?: number; web_search?: boolean; allow_commands?: string[]; deny_commands?: string[]; custom_base_url?: string; auto_commit?: boolean; reasoning_effort?: string; provider?: string }) => Promise<void>
  isAdmin: boolean
}) {
  const { t, language, setLanguage } = useI18n()
  const locked = props.settings.settings_locked ?? false
  const initialProvider = props.settings.provider ?? 'openrouter'
  type KeyProvider = 'openrouter' | 'google' | 'custom'
  const [keyProvider, setKeyProvider] = useState<KeyProvider>(() => {
    const saved = localStorage.getItem('forge-key-provider')
    return saved === 'openrouter' || saved === 'google' || saved === 'custom' ? saved : initialProvider
  })
  const providerLabel = keyProvider === 'google' ? 'Google / Gemini' : keyProvider === 'custom' ? 'Custom OpenAI-compatible' : 'OpenRouter'
  const [tab, setTab] = useState<TabId>(props.isAdmin ? 'conn' : 'ui')
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
  const selectedKeySaved = props.settings.provider_keys
    ? Boolean(props.settings.provider_keys[keyProvider])
    : keyProvider === initialProvider && Boolean(props.settings.key_masked)
  const selectedKeyMask = selectedKeySaved ? '••••••••' : ''
  const chooseKeyProvider = (next: KeyProvider) => {
    setKeyProvider(next)
    localStorage.setItem('forge-key-provider', next)
    // Không bao giờ mang draft secret từ provider này sang Save cho provider khác.
    setKey('')
    setKeyCheck(null)
  }
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
    api.keyCheck(k, keyProvider).then(setKeyCheck).catch((e) => setKeyCheck({ valid: false, error: String(e) }))
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
    if (!props.sid) { setSkillErr(t('Mở một phiên để xem skills của workspace đó.', 'Open a session to view skills for that workspace.')); return }
    setSkillErr(null)
    api.skills(props.sid).then((d) => { setSkillRows(d.skills); setSkillDiags(d.diags) })
      .catch((e) => setSkillErr(String((e as Error).message ?? e)))
  }

  // ── Private team + Google OIDC (admin) ──
  const [teamUsers, setTeamUsers] = useState<AuthUser[] | null>(null)
  const [teamEmail, setTeamEmail] = useState('')
  const [teamName, setTeamName] = useState('')
  const [teamPassword, setTeamPassword] = useState('')
  const [teamRole, setTeamRole] = useState('member')
  const [teamBusy, setTeamBusy] = useState(false)
  const [teamErr, setTeamErr] = useState<string | null>(null)
  const [googleCfg, setGoogleCfg] = useState<GoogleAuthConfig | null>(null)
  const [googleSecret, setGoogleSecret] = useState('')
  const [registrationCfg, setRegistrationCfg] = useState<{ enabled: boolean } | null>(null)
  const loadTeam = () => {
    if (!props.isAdmin) return
    api.listUsers().then(setTeamUsers).catch((e) => setTeamErr(String((e as Error).message ?? e)))
    api.googleConfig().then(setGoogleCfg).catch(() => {})
    api.registrationConfig().then(setRegistrationCfg).catch((e) => setTeamErr(String((e as Error).message ?? e)))
  }
  const invite = async () => {
    setTeamBusy(true); setTeamErr(null)
    try {
      await api.inviteUser(teamEmail.trim(), teamPassword || undefined, teamName.trim(), teamRole)
      setTeamEmail(''); setTeamName(''); setTeamPassword(''); loadTeam()
    } catch (e) { setTeamErr((e as Error).message) } finally { setTeamBusy(false) }
  }
  const saveGoogle = async () => {
    if (!googleCfg) return
    setTeamBusy(true); setTeamErr(null)
    try {
      setGoogleCfg(await api.saveGoogleConfig(googleCfg.client_id, googleSecret, googleCfg.public_url))
      setGoogleSecret('')
    } catch (e) { setTeamErr((e as Error).message) } finally { setTeamBusy(false) }
  }
  const saveRegistration = async (enabled: boolean) => {
    setTeamBusy(true); setTeamErr(null)
    try { setRegistrationCfg(await api.setRegistrationEnabled(enabled)) }
    catch (e) { setTeamErr((e as Error).message) }
    finally { setTeamBusy(false) }
  }

  // ── Audit log tab ──
  const [auditRows, setAuditRows] = useState<AuditEntry[] | null>(null)
  const [auditFilter, setAuditFilter] = useState('')
  const [auditQf, setAuditQf] = useState<'all' | 'ok' | 'bad'>('all')
  const [auditOpen, setAuditOpen] = useState<number | null>(null)
  const loadAudit = () => { setAuditOpen(null); api.audit(200).then((rows) => setAuditRows(rows)).catch(() => setAuditRows([])) }
  useEffect(() => {
    if (tab === 'audit' && auditRows === null) loadAudit()
    if (tab === 'svc' && svcPresets === null) loadSvc()
    if (tab === 'skl') loadSkills()
    if (tab === 'team' && teamUsers === null) loadTeam()
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
    if (props.isAdmin) reloadMcp()
    api.models().then((d) => setModels(d.models)).catch(() => {})
    api.usage().then(setTotals).catch(() => {})
  }, [])

  const dialogRef = useRef<HTMLDivElement>(null)
  const tryCloseRef = useRef<() => void>(() => {})
  const tryClose = () => {
    if (dirty && !confirm(t('Có thay đổi CHƯA LƯU — vẫn đóng?', 'You have UNSAVED changes — close anyway?'))) return
    props.onClose()
  }
  tryCloseRef.current = tryClose

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = dialogRef.current
    dialog?.focus()
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        tryCloseRef.current()
        return
      }
      if (e.key !== 'Tab' || !dialog) return
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      )).filter((el) => el.getClientRects().length > 0)
      if (!focusable.length) { e.preventDefault(); dialog.focus(); return }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
        e.preventDefault(); last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', h)
    return () => {
      document.removeEventListener('keydown', h)
      previous?.focus()
    }
  }, [])

  useEffect(() => {
    document.getElementById('settings-panel')?.scrollTo({ top: 0 })
  }, [tab])

  async function doSave() {
    if (locked) { setSaveErr(t('Release mode: Settings chỉ được thay đổi qua terminal.', 'Release mode: settings can only be changed through the terminal.')); return }
    const mt = Number(maxTokens)
    if (!Number.isInteger(mt) || mt < 256 || mt > 65536) {
      setTab('conn')
      setSaveErr(t('Max tokens phải là số nguyên từ 256 đến 65536.', 'Max tokens must be an integer between 256 and 65536.'))
      requestAnimationFrame(() => document.querySelector<HTMLInputElement>('.model-card input[type="number"]')?.focus())
      return
    }
    setSaving(true); setSaveErr(null)
    try {
      await props.onSave(key || undefined, model !== initial.model ? (model || undefined) : undefined, {
        approval_mode: approval,
        docker_sandbox: docker,
        web_search: webSearch,
        allow_commands: allowCmds.split('\n').map((s) => s.trim()).filter(Boolean),
        deny_commands: denyCmds.split('\n').map((s) => s.trim()).filter(Boolean),
        custom_base_url: baseUrl.trim(),
        provider: keyProvider,
        reasoning_effort: effort,
        auto_commit: autoCommit,
        ...(Number.isFinite(mt) && mt >= 256 && mt <= 65536 ? { max_tokens: mt } : {}),
      })
      props.onClose()
    } catch (e) {
      setSaveErr(t(`Không lưu được: ${(e as Error).message ?? e}`, `Could not save: ${(e as Error).message ?? e}`))
    } finally { setSaving(false) }
  }

  const filteredModels = modelFilter
    ? (modelFilter.trim().toLowerCase() === 'free'
        ? models.filter((m) => m.free)
        : models.filter((m) => m.id.toLowerCase().includes(modelFilter.toLowerCase()))
      ).slice(0, 40)
    : models.slice(0, 40)

  const visibleTabs = TABS.filter((t) => props.isAdmin || ['ui', 'skl', 'audit'].includes(t.id))
  const activeTab = visibleTabs.find((t) => t.id === tab) ?? visibleTabs[0]

  return (
    <div className="modal-backdrop" onClick={tryClose}>
      <div ref={dialogRef} className="modal modal-wide settings-modal" role="dialog" aria-modal="true"
        aria-labelledby="settings-title" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <header className="modal-head settings-head">
          <div>
            <h3><span aria-hidden="true">⚙</span> <span id="settings-title">{t('Cài đặt', 'Settings')}</span>{dirty && <span className="dirty-dot" title={t('Có thay đổi chưa lưu', 'Unsaved changes')} />}</h3>
            {totals && (
              <div className="usage-line">
                📊 <b>{totals.sessions}</b> {t('phiên', totals.sessions === 1 ? 'session' : 'sessions')} · <b>{(totals.total_tokens ?? 0).toLocaleString(language === 'en' ? 'en-US' : 'vi-VN')}</b> tokens
                {totals.cost > 0 && <> · ~${totals.cost.toFixed(4)}</>}
              </div>
            )}
          </div>
          <button className="modal-close" title={t('Đóng (Esc)', 'Close (Esc)')} aria-label={t('Đóng cài đặt', 'Close settings')} onClick={tryClose}>✕</button>
        </header>

        <div className="settings-layout">
          <nav className="settings-tabs" role="tablist" aria-label={t('Nhóm cài đặt', 'Settings groups')}
            onKeyDown={(e) => {
              const current = visibleTabs.findIndex((t) => t.id === tab)
              let next = current
              if (e.key === 'ArrowDown' || e.key === 'ArrowRight') next = (current + 1) % visibleTabs.length
              else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') next = (current - 1 + visibleTabs.length) % visibleTabs.length
              else if (e.key === 'Home') next = 0
              else if (e.key === 'End') next = visibleTabs.length - 1
              else return
              e.preventDefault()
              const id = visibleTabs[next].id
              setTab(id)
              requestAnimationFrame(() => document.getElementById(`settings-tab-${id}`)?.focus())
            }}>
            {visibleTabs.map((tabItem) => (
              <button key={tabItem.id} id={`settings-tab-${tabItem.id}`} role="tab" aria-selected={tab === tabItem.id}
                aria-controls="settings-panel" tabIndex={tab === tabItem.id ? 0 : -1}
                className={`settings-tab ${tab === tabItem.id ? 'on' : ''}`}
                onClick={() => setTab(tabItem.id)}>{t(tabItem.label[0], tabItem.label[1])}</button>
            ))}
          </nav>

          <div className="settings-body" id="settings-panel" role="tabpanel" aria-labelledby={`settings-tab-${activeTab.id}`}>
            <div className="settings-body-head">
              <h4>{t(activeTab.label[0], activeTab.label[1])}</h4>
              <p>{tab === 'conn' ? t('Provider, credentials và cách model phản hồi.', 'Providers, credentials, and model generation.') : tab === 'ui' ? t('Tuỳ chỉnh hiển thị trên thiết bị này.', 'Display preferences for this device.') : tab === 'safe' ? t('Kiểm soát shell, quyền chạy lệnh và checkpoint.', 'Control shell execution, approvals, and checkpoints.') : tab === 'team' ? t('Tài khoản team và đăng nhập Google.', 'Team accounts and Google sign-in.') : tab === 'sys' ? t('Chẩn đoán môi trường và ranh giới dữ liệu.', 'Environment diagnostics and data boundaries.') : t('Quản lý và theo dõi khả năng của Forge.', 'Manage and monitor Forge capabilities.')}</p>
            </div>
        {tab === 'conn' && (
          <>
            {locked && (
              <div className="field release-lock-banner" role="status">
                🔒 <b>Release mode</b> — {t('cấu hình chỉ được sửa qua terminal trên server. Không thể đọc hoặc thay API key từ trang này.', 'configuration can only be changed through the server terminal. API keys cannot be read or replaced on this page.')}
              </div>
            )}
            <div className="connection-grid">
              <section className="settings-card provider-card" aria-labelledby="provider-card-title">
                <div className="settings-card-head">
                  <div><h5 id="provider-card-title">Provider &amp; credentials</h5><p>{t('Key được giữ riêng cho từng provider.', 'Keys are stored separately for each provider.')}</p></div>
                  <span className="card-icon" aria-hidden="true">🔐</span>
                </div>
                {props.isAdmin && <div className="field">
                  <span>{t('Provider của API key', 'API key provider')} <em>{t('(không đổi default routing)', '(does not change default routing)')}</em></span>
                  <select aria-label={t('Provider của API key', 'API key provider')} value={keyProvider}
                    onChange={(e) => chooseKeyProvider(e.target.value as KeyProvider)} disabled={locked}>
                    <option value="openrouter">OpenRouter</option>
                    <option value="google">Google Gemini direct</option>
                    <option value="custom">Custom OpenAI-compatible</option>
                  </select>
                  <div className="provider-key-status" aria-label={t('Trạng thái API key các provider', 'Provider API key status')}>
                    {([
                      ['openrouter', 'OpenRouter'],
                      ['google', 'Google'],
                      ['custom', 'Custom'],
                    ] as const).map(([id, label]) => {
                      const saved = Boolean(props.settings.provider_keys?.[id])
                      return <button type="button" key={id} className={id === keyProvider ? 'on' : ''}
                        aria-pressed={id === keyProvider} onClick={() => chooseKeyProvider(id)} disabled={locked}>
                        {label}: {saved ? t('✓ đã lưu', '✓ saved') : t('— chưa lưu', '— not saved')}
                      </button>
                    })}
                  </div>
                  <small>{t('Lưu độc lập trong secret store phía server. Đổi provider sẽ xoá draft key để tránh lưu nhầm.', 'Stored independently in the server secret store. Switching providers clears the draft key to prevent accidental saves.')}</small>
                </div>}
                {props.isAdmin && keyProvider === 'custom' && <label className="field">
                  <span>Custom base URL <em>(Ollama/LM Studio/vLLM)</em></span>
                  <input placeholder={t('vd: http://localhost:11434/v1', 'e.g. http://localhost:11434/v1')} value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)} />
                  <small>{t('Dán URL rồi đặt Model thành tên cục bộ. Để trống nếu không dùng custom endpoint.', 'Paste the URL and set Model to your local model name. Leave empty when not using a custom endpoint.')}</small>
                </label>}
                {props.settings.web_key_input === false ? (
                  <div className="field release-key-status">
                    <span>🔐 {providerLabel} credentials</span>
                    <small>{t('Trạng thái:', 'Status:')} <b>{selectedKeyMask || t('chưa có key', 'no key')}</b>. {t('Key chỉ được nhập bằng terminal:', 'Keys can only be entered through the terminal:')} <code>python scripts/setup_keys.py</code>.</small>
                  </div>
                ) : (
                  <label className="field">
                    <span>{providerLabel} API Key {selectedKeyMask && <em>({t('đã lưu:', 'saved:')} {selectedKeyMask})</em>}</span>
                    <div className="key-row">
                      <input type="password" autoComplete="off" aria-label={`${providerLabel} API Key`}
                        placeholder={selectedKeySaved ? t('Đã lưu key — nhập key mới để thay thế', 'Key saved — enter a new key to replace it') : keyProvider === 'google' ? 'AIza...' : keyProvider === 'custom' ? t('API key (nếu cần)', 'API key (if required)') : 'sk-or-v1-...'} value={key}
                        onChange={(e) => { setKey(e.target.value); setKeyCheck(null) }} />
                      {keyProvider !== 'custom' && (
                        <button className="btn-ghost btn-sm" disabled={checking}
                          onClick={() => doKeyCheck(key || undefined)}>
                          {checking ? t('Đang kiểm tra…', 'Checking…') : key.trim() ? t('🔍 Kiểm tra key mới', '🔍 Check new key') : t('🔍 Kiểm tra key đã lưu', '🔍 Check saved key')}
                        </button>
                      )}
                    </div>
                    {keyProvider === 'google' ? (
                      <small>{t('Tạo key tại', 'Create a key at')} <a href="https://aistudio.google.com/api-keys" target="_blank" rel="noreferrer">Google AI Studio</a>. {t('Không gửi code bí mật khi dùng Free Tier.', 'Do not send confidential code when using the Free Tier.')}</small>
                    ) : keyProvider === 'custom' ? (
                      <small>{t('Key cho server OpenAI-compatible; để trống nếu không đổi. Ollama thường không cần key.', 'Key for the OpenAI-compatible server; leave empty to keep it unchanged. Ollama usually does not need a key.')}</small>
                    ) : (
                      <small>{t('Lấy key tại', 'Get a key at')} <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">openrouter.ai/keys</a> — {t('để trống nếu không đổi.', 'leave empty to keep it unchanged.')}</small>
                    )}
                    <small className="key-privacy-note">{t('Forge không trả lại secret thô. “Đã lưu” áp dụng đúng provider đang chọn; Save với ô trống giữ nguyên key.', 'Forge never returns the raw secret. “Saved” applies to the selected provider; saving with an empty field keeps the existing key.')}</small>
                    {keyCheck && (keyCheck.valid ? (
                      <div className="key-result ok">{t('✅ Key hợp lệ', '✅ Valid key')} — «{keyCheck.label}»{keyCheck.usage != null && <> · {t('đã dùng', 'used')} ${keyCheck.usage}</>}{keyCheck.limit != null ? t(` / hạn mức $${keyCheck.limit}`, ` / limit $${keyCheck.limit}`) : ''}{keyCheck.is_free_tier && ' · free tier'}</div>
                    ) : (
                      <div className="key-result bad">❌ {keyCheck.error}{keyCheck.hint && <div className="key-hint">💡 {keyCheck.hint}</div>}</div>
                    ))}
                  </label>
                )}
              </section>

              <section className="settings-card model-card" aria-labelledby="model-card-title">
                <div className="settings-card-head">
                  <div><h5 id="model-card-title">Model &amp; generation</h5><p>{t('Model mặc định; áp dụng cho phiên hiện tại khi Save.', 'Default model; also applies to the current session when saved.')}</p></div>
                  <span className="card-icon" aria-hidden="true">⚡</span>
                </div>
                <div className="field">
                  <span>{t('Model mặc định', 'Default model')} <em>({models.length > 0 ? t(`${models.length} model trong registry`, `${models.length} models in registry`) : t('đang đồng bộ…', 'syncing…')})</em></span>
                  <input list="models" aria-label={t('Model mặc định', 'Default model')} value={model} onChange={(e) => setModel(e.target.value)} />
                  <datalist id="models">
                    {(models.length ? models.map((m) => m.id) : props.settings.default_models).map((m) => <option key={m} value={m} />)}
                  </datalist>
                  <div className="filter-presets" aria-label={t('Bộ lọc model nhanh', 'Quick model filters')}>
                    <button className={`preset ${modelFilter === 'free' ? 'on' : ''}`} onClick={() => setModelFilter(modelFilter === 'free' ? '' : 'free')}>{t('🆓 Miễn phí', '🆓 Free')}</button>
                    <button className={`preset ${modelFilter === 'claude' ? 'on' : ''}`} onClick={() => setModelFilter('claude')}>Claude</button>
                    <button className={`preset ${modelFilter === 'gpt' ? 'on' : ''}`} onClick={() => setModelFilter('gpt')}>GPT</button>
                    <button className={`preset ${modelFilter === 'coder' ? 'on' : ''}`} onClick={() => setModelFilter('coder')}>Coder</button>
                  </div>
                  <input className="model-filter" aria-label={t('Lọc danh sách model', 'Filter model list')}
                    placeholder={t("Tìm theo tên hoặc gõ 'free'…", "Search by name or type 'free'…")} value={modelFilter}
                    onChange={(e) => setModelFilter(e.target.value)} />
                  <div className="model-suggest">
                    {filteredModels.map((m) => (
                      <button key={m.id} className={`model-chip ${m.free ? 'free-chip' : ''}`}
                        title={`${m.name} · context ${m.context ?? '?'} · ${m.free ? t('MIỄN PHÍ', 'FREE') : `$${(m.prompt_price * 1e6).toFixed(2)}/M in · $${(m.completion_price * 1e6).toFixed(2)}/M out`}`}
                        onClick={() => { setModel(m.id); setModelFilter('') }}>
                        {m.free ? '🆓 ' : ''}{m.id}
                      </button>
                    ))}
                  </div>
                  <small>{t('Chưa nạp credit? Chọn model 🆓 như', 'No credits yet? Choose a 🆓 model such as')} <code>openrouter:openrouter/free</code>.</small>
                </div>
                <div className="field">
                  <span>{t('Effort suy luận', 'Reasoning effort')} <em>{t('(reasoning budget qua OpenRouter)', '(reasoning budget through OpenRouter)')}</em></span>
                  <select aria-label={t('Effort suy luận', 'Reasoning effort')} value={effort} onChange={(e) => setEffort(e.target.value)}>
                    <option value="">{t('Mặc định của model', 'Model default')}</option>
                    <option value="low">{t('Low — nhanh, rẻ', 'Low — fast and inexpensive')}</option>
                    <option value="medium">{t('Medium — cân bằng', 'Medium — balanced')}</option>
                    <option value="high">{t('High — suy luận sâu', 'High — deeper reasoning')}</option>
                  </select>
                </div>
                <label className="field">
                  <span>{t('Max tokens mỗi phản hồi', 'Max tokens per response')}</span>
                  <input type="number" min={256} max={65536} step={256} value={maxTokens}
                    onChange={(e) => setMaxTokens(e.target.value)} />
                  <small>{t('Mặc định 16384. Giảm xuống 4096 nếu cần giới hạn credit đặt cọc.', 'Default: 16384. Reduce to 4096 to limit credit usage.')}</small>
                </label>
                <label className="field check compact-check">
                  <input type="checkbox" checked={webSearch} onChange={(e) => setWebSearch(e.target.checked)} />
                  <span>🌐 Web search <em>— {t('thêm', 'adds')} <code>:online</code>, {t('phí theo provider', 'provider fees apply')}</em></span>
                </label>
              </section>
            </div>
          </>
        )}

        {tab === 'ui' && (
          <section className="settings-card appearance-card" aria-labelledby="appearance-title">
            <div className="settings-card-head">
              <div><h5 id="appearance-title">{t('Theme hiển thị', 'Display theme')}</h5><p>{t('Áp dụng ngay và lưu trên thiết bị này.', 'Applied immediately and saved on this device.')}</p></div>
              <span className="card-icon" aria-hidden="true">🎨</span>
            </div>
            <div className="theme-options">
              {THEMES.map((themeOption) => <button key={themeOption.id} className={`theme-option ${theme === themeOption.id ? 'on' : ''}`}
                aria-pressed={theme === themeOption.id} onClick={() => applyTheme(themeOption.id)}>{t(themeOption.label[0], themeOption.label[1])}<span>{theme === themeOption.id ? '✓' : ''}</span></button>)}
            </div>
            <div className="appearance-divider">
              <div className="settings-card-head">
                <div><h5>{t('Ngôn ngữ giao diện', 'Interface language')}</h5><p>{t('Chọn ngôn ngữ cho nhãn và điều khiển Web UI.', 'Choose the language for Web UI labels and controls.')}</p></div>
                <span className="card-icon" aria-hidden="true">🌐</span>
              </div>
              <div className="theme-options" role="group" aria-label={t('Ngôn ngữ giao diện', 'Interface language')}>
                <button className={`theme-option ${language === 'vi' ? 'on' : ''}`} aria-pressed={language === 'vi'} onClick={() => setLanguage('vi')}>Tiếng Việt<span>{language === 'vi' ? '✓' : ''}</span></button>
                <button className={`theme-option ${language === 'en' ? 'on' : ''}`} aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>English<span>{language === 'en' ? '✓' : ''}</span></button>
              </div>
            </div>
            <div className="appearance-note">{t('Theme và ngôn ngữ là tuỳ chọn cá nhân, không thay đổi dữ liệu hoặc quyền truy cập.', 'Theme and language are personal preferences; they do not change data or access permissions.')}</div>
          </section>
        )}

        {tab === 'safe' && (
          <>
            <div className="field">
              <span>{t('Chế độ duyệt lệnh shell', 'Shell command approval mode')}</span>
              <div className="seg seg-3">
                <button className={`seg-btn ${approval === 'guarded' ? 'on' : ''}`}
                  onClick={() => setApproval('guarded')}>
                  🛡 Guarded<span className="seg-desc">{t('chặn lệnh nguy hiểm', 'block dangerous commands')}</span>
                </button>
                <button className={`seg-btn ${approval === 'ask' ? 'on' : ''}`}
                  onClick={() => setApproval('ask')}>
                  {t('🔔 Hỏi từng lệnh', '🔔 Ask every time')}<span className="seg-desc">{t('popup phê duyệt warn/danger', 'approval popup for warn/danger')}</span>
                </button>
                <button className={`seg-btn ${approval === 'auto' ? 'on' : ''}`}
                  onClick={() => setApproval('auto')}>
                  ⚡ Auto (YOLO)<span className="seg-desc">{t('chạy mọi lệnh — rủi ro tự chịu', 'run every command at your own risk')}</span>
                </button>
              </div>
            </div>

            {props.settings.docker_available && (
              <label className="field check">
                <input type="checkbox" checked={docker} onChange={(e) => setDocker(e.target.checked)} />
                <span>{t('🐳 Chạy lệnh trong Docker sandbox (không mạng, giới hạn CPU/RAM)', '🐳 Run commands in a Docker sandbox (no network, CPU/RAM limits)')}</span>
              </label>
            )}

            <label className="field check">
              <input type="checkbox" checked={autoCommit} onChange={(e) => setAutoCommit(e.target.checked)} />
              <span>{t('📦 Auto-commit mỗi lượt', '📦 Auto-commit each turn')} <em>— {t('git init workspace (nếu chưa có) và commit thay đổi với message Conventional Commits do model rẻ sinh (theo pattern Aider). Xem', 'initialize a git workspace if needed and commit changes with a Conventional Commits message generated by a cheaper model (Aider pattern). See')} <code>git log</code> {t('trong workspace.', 'in the workspace.')}</em></span>
            </label>

            <div className="field">
              <span>Permission patterns <em>(glob, {t('mỗi dòng 1 mẫu — vd', 'one pattern per line — e.g.')} <code>git *</code>, <code>npm run *</code>)</em></span>
              <div className="perm-grid">
                <div className="perm-col">
                  <small className="perm-label" style={{ color: 'var(--green)' }}>{t('✓ Allow (nâng warn → được chạy)', '✓ Allow (promote warn → allowed)')}</small>
                  <textarea className="perm-area" value={allowCmds} onChange={(e) => setAllowCmds(e.target.value)} rows={4}
                    placeholder={'git status\nnpm run *\npytest *'} />
                </div>
                <div className="perm-col">
                  <small className="perm-label" style={{ color: 'var(--red)' }}>{t('✕ Deny (chặn tuyệt đối)', '✕ Deny (always blocked)')}</small>
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
              <span>MCP servers <em>(Model Context Protocol — {t('nối tool bên ngoài vào agent', 'connect external tools to the agent')})</em></span>
              <div className="mcp-list">
                {mcp.length === 0 && <div className="empty" style={{ padding: 10 }}>{t('Chưa có server nào.', 'No servers configured.')}</div>}
                {mcp.map((s) => (
                  <div key={s.name} className="mcp-item">
                    <span className={`st ${STATUS_STYLE[s.status] ?? 'st-dim'}`}>{s.status}</span>
                    <div className="mcp-info">
                      <b>{s.name}</b> <code>{s.command} {s.args.join(' ')}</code>
                      <div className="mcp-tools">{s.tools.length ? s.tools.join(', ') : (s.error ?? '—')}</div>
                    </div>
                    <div className="mcp-actions">
                      <button title={t('Khởi động lại', 'Restart')} onClick={() => api.mcpRefresh(s.name).then(setMcp)}>⟳</button>
                      <button title={t('Gỡ', 'Remove')} onClick={() => confirm(t(`Gỡ ${s.name}?`, `Remove ${s.name}?`)) && api.mcpRemove(s.name).then(setMcp)}>🗑</button>
                    </div>
                  </div>
                ))}
              </div>
              <div className="mcp-add">
                <input placeholder={t('tên (vd: fs)', 'name (e.g. fs)')} value={mcpName} onChange={(e) => setMcpName(e.target.value)} />
                <input placeholder={t('lệnh (vd: npx)', 'command (e.g. npx)')} value={mcpCmd} onChange={(e) => setMcpCmd(e.target.value)} />
                <input placeholder={t('tham số, cách nhau bởi dấu phẩy', 'arguments, comma-separated')} value={mcpArgs} onChange={(e) => setMcpArgs(e.target.value)} />
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
                      setMcpErr(t(`Không thêm được server: ${(e as Error).message ?? e}`, `Could not add server: ${(e as Error).message ?? e}`))
                    }
                  }}
                >{t('＋ Thêm', '＋ Add')}</button>
              </div>
              {mcpErr && <div className="save-error">{mcpErr}</div>}
              <small>{t('VD: filesystem server —', 'Example: filesystem server —')} <code>npx</code> + <code>-y, @modelcontextprotocol/server-filesystem, /tmp/du-lieu</code>. {t('Agent sẽ nhận thêm tool', 'The agent automatically receives')} <code>mcp_fs_*</code> {t('tự động.', 'tools.')}</small>
            </div>
          </>
        )}

        {tab === 'svc' && (
          <>
            <div className="field">
              <span>{t('Dịch vụ & connectors', 'Services & connectors')} <em>(OAuth 2.1 — {t('đăng nhập trong trình duyệt, token lưu secrets.json chmod 600', 'browser sign-in, tokens stored in secrets.json with chmod 600')})</em></span>
              <div className="svc-list">
                {!svcPresets && <div className="empty" style={{ padding: 10 }}>{t('Đang nạp…', 'Loading…')}</div>}
                {svcPresets && svcPresets.map((p) => (
                  <div key={p.id} className="svc-row">
                    <div className="svc-head">
                      <b>{p.label.split(' — ')[0]}</b>
                      {p.connected ? <span className="st st-ok">{t('đã kết nối', 'connected')} {p.masked ? `· ${p.masked}` : ''}</span>
                        : <span className={`st ${p.installed ? 'st-warn' : 'st-dim'}`}>{p.installed ? t('chưa đăng nhập', 'not signed in') : t('chưa cài', 'not installed')}</span>}
                      {!p.installed ? (
                        <button className="btn-primary btn-sm" onClick={() => api.connectorInstall(p.id).then(loadSvc).catch(() => {})}>{t('＋ Cài', '＋ Install')}</button>
                      ) : (
                        <button className="btn-ghost btn-sm" onClick={() => confirm(t(`Gỡ '${p.label.split(' — ')[0]}'?`, `Remove '${p.label.split(' — ')[0]}'?`)) && api.connectorRemove(p.id).then(loadSvc).catch(() => {})}>{t('🗑 Gỡ', '🗑 Remove')}</button>
                      )}
                      {p.oauth && p.connected && (
                        <button className="btn-ghost btn-sm" onClick={() => api.oauthDisconnect(p.id).then(loadSvc)}>{t('Đăng xuất', 'Sign out')}</button>
                      )}
                    </div>
                    {p.oauth && (
                      <div className="svc-oauth">
                        {!p.connected && (
                          <>
                            <input placeholder="client_id" value={svcCreds[p.id]?.cid ?? ''}
                              onChange={(e) => setSvcCreds({ ...svcCreds, [p.id]: { cid: e.target.value, csec: svcCreds[p.id]?.csec ?? '' } })} />
                            <input placeholder={t('client_secret (nếu có)', 'client_secret (if any)')} type="password" value={svcCreds[p.id]?.csec ?? ''}
                              onChange={(e) => setSvcCreds({ ...svcCreds, [p.id]: { cid: svcCreds[p.id]?.cid ?? '', csec: e.target.value } })} />
                            <button className="btn-primary btn-sm" disabled={svcBusy === p.id}
                              onClick={() => { void svcConnect(p.id) }}>
                              {svcBusy === p.id ? t('⏳ Chờ duyệt trong trình duyệt…', '⏳ Waiting for browser approval…') : t('🔗 Kết nối (OAuth)', '🔗 Connect (OAuth)')}
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
              <small>{t('Flow chuẩn OAuth 2.1: PKCE S256 + loopback 127.0.0.1:8765/callback + state chống CSRF. Preset chưa OAuth: cài qua', 'Standard OAuth 2.1 flow: PKCE S256 + loopback 127.0.0.1:8765/callback + CSRF state. For presets without OAuth, install with')} <code>/connectors add</code>.</small>
            </div>
          </>
        )}
        {tab === 'team' && props.isAdmin && (
          <>
            <div className="field">
              <span>👥 Team &amp; access <em>({t('invite + public signup tùy chọn', 'invitations + optional public signup')})</em></span>
              <label className="registration-toggle">
                <input type="checkbox" checked={registrationCfg?.enabled ?? false}
                  disabled={teamBusy || registrationCfg === null}
                  onChange={(e) => saveRegistration(e.target.checked)} />
                <span>{t('Cho phép tự đăng ký tài khoản member', 'Allow public member registration')}</span>
              </label>
              <small>{t('Mặc định tắt. Endpoint có CSRF + rate-limit theo IP/email; tài khoản mới không bao giờ là admin. Email/password tự đăng ký chưa xác minh quyền sở hữu email — cân nhắc gateway quota/CAPTCHA khi mở public Internet.', 'Disabled by default. The endpoint uses CSRF and IP/email rate limits; new accounts are never admins. Email/password registration does not verify email ownership — consider gateway quotas and CAPTCHA before exposing it to the public Internet.')}</small>
              <small>{t('User Google-only: để password trống; họ đăng nhập bằng Google có cùng email đã được mời. Disable sẽ revoke session ngay.', 'For Google-only users, leave the password empty; they sign in with Google using the invited email. Disabling a user revokes sessions immediately.')}</small>
              <div className="perm-grid">
                <input type="email" placeholder="email@team.com" value={teamEmail} onChange={(e) => setTeamEmail(e.target.value)} />
                <input placeholder={t('Tên hiển thị', 'Display name')} value={teamName} onChange={(e) => setTeamName(e.target.value)} />
              </div>
              <div className="perm-grid">
                <input type="password" placeholder={t('Password ≥16 ký tự (tuỳ chọn)', 'Password ≥16 characters (optional)')} value={teamPassword} onChange={(e) => setTeamPassword(e.target.value)} />
                <select value={teamRole} onChange={(e) => setTeamRole(e.target.value)}><option value="member">Member</option><option value="admin">Admin</option></select>
              </div>
              <button className="btn-primary btn-sm" disabled={teamBusy || !teamEmail.trim()} onClick={invite}>{t('＋ Tạo / mời user', '＋ Create / invite user')}</button>
            </div>
            {teamErr && <div className="key-result bad">{teamErr}</div>}
            <div className="audit-list">
              {(teamUsers ?? []).map((u) => (
                <div className="audit-row" key={u.id}>
                  <span style={{ flex: 1 }}><b>{u.name || u.email}</b><br /><small>{u.email} · {u.role}{u.google_linked ? ' · Google' : ''}{u.password_set ? ' · password' : ''}</small></span>
                  <span className={`audit-chip ${u.enabled ? 'st-ok' : 'st-bad'}`}>{u.enabled ? 'active' : 'disabled'}</span>
                  <button className="btn-ghost btn-sm" onClick={() => api.setUserEnabled(u.id, !u.enabled).then(loadTeam).catch((e) => setTeamErr((e as Error).message))}>
                    {u.enabled ? 'Disable' : 'Enable'}
                  </button>
                </div>
              ))}
            </div>
            <div className="field" style={{ marginTop: 18 }}>
              <span>Google OpenID Connect <em>({t('chỉ login, KHÔNG xin Gmail scope', 'sign-in only, NO Gmail scope')})</em></span>
              <small>Redirect URI: <code>{googleCfg?.public_url ? `${googleCfg.public_url}/api/auth/google/callback` : 'https://forge.example/api/auth/google/callback'}</code>. {t('Public URL production phải HTTPS.', 'Production public URLs must use HTTPS.')}</small>
              <input placeholder="Google OAuth client ID" value={googleCfg?.client_id ?? ''} onChange={(e) => setGoogleCfg((old) => old ? { ...old, client_id: e.target.value } : { configured: false, client_id: e.target.value, public_url: window.location.origin, client_secret_set: false })} />
              <input type="password" placeholder={googleCfg?.client_secret_set ? t('Client secret (để trống = giữ nguyên)', 'Client secret (leave empty to keep unchanged)') : 'Google OAuth client secret'} value={googleSecret} onChange={(e) => setGoogleSecret(e.target.value)} />
              <input placeholder="https://forge.example" value={googleCfg?.public_url ?? ''} onChange={(e) => setGoogleCfg((old) => old ? { ...old, public_url: e.target.value } : { configured: false, client_id: '', public_url: e.target.value, client_secret_set: false })} />
              <button className="btn-primary btn-sm" disabled={teamBusy || !googleCfg?.client_id || !googleCfg.public_url} onClick={saveGoogle}>{t('Lưu Google login', 'Save Google sign-in')}</button>
            </div>
          </>
        )}

        {tab === 'skl' && (
          <>
            <div className="field">
              <span>Skills <em>({t('chuẩn SKILL.md — quét .forge/skills · .agents/skills · .claude/skills · ~/.forge/skills', 'SKILL.md standard — scans .forge/skills · .agents/skills · .claude/skills · ~/.forge/skills')})</em></span>
              {skillErr && <div className="save-error">{skillErr}</div>}
              {!skillErr && (
                <div className="skill-list">
                  {!skillRows && <div className="empty" style={{ padding: 10 }}>{t('Đang nạp…', 'Loading…')}</div>}
                  {skillRows && skillRows.length === 0 && (
                    <div className="empty" style={{ padding: 10 }}>{t('Chưa có skill nào —', 'No skills yet — use')} <code>{t('/skills new <tên>', '/skills new <name>')}</code> {t('để tạo.', 'to create one.')}</div>
                  )}
                  {skillRows && skillRows.map((k) => (
                    <div key={k.path} className={`skill-row ${k.trusted ? '' : 'untrusted'}`}>
                      <div className="skill-head">
                        <b>{k.name}</b>
                        {k.fmt === 'standard' ? <span className="st st-dim">standard</span> : <span className="st st-dim">legacy</span>}
                        {!k.trusted && <span className="st st-warn">{t('🔒 chưa tin', '🔒 untrusted')}</span>}
                        {!k.model_invocable && <span className="st st-dim">{t('🔕 chỉ gọi tay', '🔕 manual only')}</span>}
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
                          {skillBusy === k.path ? '…' : k.model_invocable ? t('🔕 Cấm model gọi', '🔕 Disable model invocation') : t('✅ Cho model gọi', '✅ Allow model invocation')}
                        </button>
                        {!k.trusted && k.source === 'project' && (
                          <button className="btn-primary btn-sm" disabled={skillBusy === k.path}
                            onClick={() => { setSkillBusy(k.path)
                              api.skillTrust(props.sid as string, k.name)
                                .then(() => api.skills(props.sid as string)).then((d) => { setSkillRows(d.skills); setSkillDiags(d.diags) })
                                .catch(() => {}).finally(() => setSkillBusy(null)) }}>
                            {t('🔓 Tin skill này', '🔓 Trust this skill')}
                          </button>
                        )}
                      </div>
                      <code className="skill-path">{k.path}</code>
                    </div>
                  ))}
                </div>
              )}
              {skillDiags.length > 0 && (
                <small>⚠ {skillDiags.length} {t('cảnh báo diagnostics:', 'diagnostic warnings:')} {skillDiags.slice(0, 3).join(' · ')}</small>
              )}
              <small>{t('Bật/tắt chỉ đổi frontmatter', 'Toggling only changes the')} <code>disable-model-invocation</code> {t('trong SKILL.md — hiệu lực ngay.', 'frontmatter in SKILL.md and takes effect immediately.')}</small>
            </div>
          </>
        )}
        {tab === 'audit' && (
          <>
            <div className="field">
              <span>Audit log <em>({t('mọi tool call của agent — token tự mask, file data/audit/', 'every agent tool call — tokens are masked automatically, stored in data/audit/')})</em></span>
              <div className="audit-bar">
                <input
                  placeholder={t('Lọc theo tool/nguồn/đối số/phiên…', 'Filter by tool/source/arguments/session…')}
                  value={auditFilter}
                  onChange={(e) => setAuditFilter(e.target.value)}
                />
                <button className={`btn-ghost btn-sm audit-chip ${auditQf === 'all' ? 'on' : ''}`} onClick={() => setAuditQf('all')}>{t('Tất cả', 'All')}</button>
                <button className={`btn-ghost btn-sm audit-chip ${auditQf === 'ok' ? 'on' : ''}`} onClick={() => setAuditQf('ok')}>✅</button>
                <button className={`btn-ghost btn-sm audit-chip ${auditQf === 'bad' ? 'on' : ''}`} onClick={() => setAuditQf('bad')}>❌</button>
                <button className="btn-ghost btn-sm" onClick={() => { setAuditRows(null); loadAudit() }}>{t('⟳ Nạp lại', '⟳ Reload')}</button>
                <a className="btn-ghost btn-sm" href="/api/audit/export" download title={t('Tải tối đa 2000 mục mới nhất (CSV)', 'Download up to 2000 latest entries (CSV)')}>{t('⤓ Xuất CSV', '⤓ Export CSV')}</a>
              </div>
              <div className="audit-list">
                {!auditRows && <div className="empty" style={{ padding: 10 }}>{t('Đang nạp…', 'Loading…')}</div>}
                {auditRows && auditRows.length === 0 && (
                  <div className="empty" style={{ padding: 10 }}>{t('Chưa có tool call nào — cho agent chạy một lượt rồi quay lại.', 'No tool calls yet — run the agent for a turn and come back.')}</div>
                )}
                {auditRows && auditRows
                  .filter((e) => {
                    if (auditQf === 'ok' && !e.ok) return false
                    if (auditQf === 'bad' && e.ok) return false
                    if (!auditFilter.trim()) return true
                    const q = auditFilter.toLowerCase()
                    return (e.tool + ' ' + e.source + ' ' + (e.session ?? '') + ' ' + JSON.stringify(e.args ?? {}) + ' ' + (e.note ?? '')).toLowerCase().includes(q)
                  })
                  .map((e, i) => (
                    <div key={i} style={{ display: 'contents' }}>
                      <div className={`audit-row ${e.ok ? '' : 'bad'} click`} onClick={() => setAuditOpen(auditOpen === i ? null : i)}
                        title={t('Bấm để xem chi tiết đầy đủ', 'Click to view full details')}>
                        <span className="audit-ts">{String(e.ts).slice(11, 19)}</span>
                        <span className="audit-ok">{e.ok ? '✅' : '❌'}</span>
                        <b className="audit-tool">{e.tool}</b>
                        <span className="audit-src">{e.source}</span>
                        <span className="audit-sid" title={t(`Phiên: ${e.session ?? '—'}`, `Session: ${e.session ?? '—'}`)}>{String(e.session ?? '').slice(-6) || '—'}</span>
                        <span className="audit-ms">{e.ms != null ? `${e.ms}ms` : '—'}</span>
                        <span className="audit-args">
                          {Object.entries(e.args ?? {}).map(([k, v]) => `${k}=${v}`).join(' ').slice(0, 90)}
                          {e.note ? ` · ${e.note}` : ''}
                        </span>
                      </div>
                      {auditOpen === i && (
                        <div className="audit-detail">
                          <div><b>{e.tool}</b> · {String(e.ts)} · {e.ms != null ? `${e.ms}ms` : '—'}</div>
                          <div>{t('phiên:', 'session:')} <code>{e.session || '—'}</code> · {t('nguồn:', 'source:')} {e.source}</div>
                          {e.note && <div>{t('ghi chú:', 'note:')} {e.note}</div>}
                          <pre>{JSON.stringify(e.args ?? {}, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  ))}
              </div>
              <small>{t('Hiển thị tối đa 200 mục mới nhất. Xem đầy đủ:', 'Showing up to 200 latest entries. View everything with')} <code>/audit</code> {t('hoặc', 'or')} <code>{t('data/audit/<ngày>.jsonl', 'data/audit/<date>.jsonl')}</code></small>
            </div>
          </>
        )}
        {tab === 'sys' && (
          <>
            <div className="field">
              <span>{t('Chẩn đoán hệ thống', 'System diagnostics')} <em>({t('kiểm tra Python, git, key, model, LSP, MCP…', 'check Python, git, keys, models, LSP, MCP…')})</em></span>
              <button className="btn-ghost" disabled={doctoring}
                onClick={async () => {
                  setDoctoring(true)
                  try { setDoctorRep(await api.doctor()) } catch { /* ignore */ }
                  finally { setDoctoring(false) }
                }}>
                {doctoring ? t('Đang chẩn đoán…', 'Running diagnostics…') : t('🩺 Chạy chẩn đoán', '🩺 Run diagnostics')}
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
              <span>{t('Bảo mật & dữ liệu', 'Security & data')}</span>
              <small style={{ lineHeight: 1.7 }}>
                🔐 {t('Provider key lưu trong', 'Provider keys are stored in')} <code>data/provider-secrets.json</code> {t('trên server (chmod 600 khi hỗ trợ), không đưa vào git/zip. User password và session token chỉ lưu hash.', 'on the server (chmod 600 where supported), never in git or ZIP archives. User passwords and session tokens are stored only as hashes.')}<br />
                🧩 {t('Shell/hook/subprocess của agent bị loại key LLM/admin khỏi environment.', 'Agent shells, hooks, and subprocesses have LLM and admin keys removed from their environment.')}<br />
                🛡 {t('Guarded mode chặn lệnh nguy hiểm (', 'Guarded mode blocks dangerous commands (')}<code>sudo</code>, <code>rm -rf /</code>, {t('pipe-từ-mạng…', 'network pipes…')}).<br />
                💾 {t('Checkpoint: mọi thay đổi file của agent đều có bản git nội bộ — nút ↩ Undo hoàn tác được.', 'Checkpoints: every agent file change has an internal git checkpoint that can be undone with ↩ Undo.')}
              </small>
            </div>
          </>
        )}
          </div>
        </div>

        <footer className="settings-footer">
          {saveErr && <div className="save-error" role="alert">{saveErr}</div>}
          <div className="modal-actions">
            <span className="save-state-text">{props.isAdmin ? (dirty ? t('● Có thay đổi chưa lưu', '● Unsaved changes') : t('Mọi thay đổi đã được lưu', 'All changes saved')) : t('Tuỳ chọn theo quyền member', 'Options available to members')}</span>
            <div>
              <button className="btn-ghost btn-sm" onClick={tryClose}>{t('Đóng', 'Close')}</button>
              {props.isAdmin && <button
                className="btn-primary"
                disabled={saving || !dirty || locked}
                title={locked ? t('Release mode: cấu hình qua terminal', 'Release mode: configure through the terminal') : dirty ? t('Áp dụng các thay đổi', 'Apply changes') : t('Chưa có thay đổi nào', 'No changes yet')}
                onClick={doSave}
              >{locked ? t('🔒 Settings đã khóa', '🔒 Settings locked') : saving ? t('Đang lưu…', 'Saving…') : dirty ? t('💾 Lưu thay đổi', '💾 Save changes') : t('Lưu cài đặt', 'Save settings')}</button>}
            </div>
          </div>
        </footer>
      </div>
    </div>
  )
}
