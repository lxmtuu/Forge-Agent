import React, { useState } from 'react'
import { api } from '../api'
import type { AuthUser } from '../api'

const OAUTH_ERRORS: Record<string, string> = {
  google_denied: 'Bạn đã huỷ đăng nhập Google.',
  google_state: 'Phiên đăng nhập Google không hợp lệ hoặc đã hết hạn.',
  google_replay: 'Luồng đăng nhập Google đã được dùng. Hãy bắt đầu lại.',
  google_invalid: 'Không xác minh được danh tính Google.',
  not_invited: 'Email chưa được admin mời, hoặc tự đăng ký đang tắt.',
  disabled: 'Tài khoản đang bị vô hiệu hoá.',
}

export function LoginScreen(props: {
  googleEnabled: boolean
  registrationEnabled: boolean
  needsSetup: boolean
  onLoggedIn: (user: AuthUser) => void
}) {
  const params = new URLSearchParams(window.location.search)
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(OAUTH_ERRORS[params.get('error') ?? ''] ?? null)
  const registering = mode === 'register'

  function switchMode(next: 'login' | 'register') {
    setMode(next); setError(null); setPassword(''); setConfirm('')
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    if (registering && password.length < 16) {
      setError('Mật khẩu phải có ít nhất 16 ký tự.')
      return
    }
    if (registering && password !== confirm) {
      setError('Mật khẩu xác nhận không khớp.')
      return
    }
    setBusy(true); setError(null)
    try {
      const user = registering
        ? await api.register(email.trim(), password, name.trim())
        : await api.login(email.trim(), password)
      window.history.replaceState({}, '', '/')
      props.onLoggedIn(user)
    } catch (err) {
      setError((err as Error).message)
    } finally { setBusy(false) }
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-brand"><span className="login-bolt">⚡</span> Forge <em>agent</em></div>
        <h1 id="login-title">{registering ? 'Tạo tài khoản member' : props.registrationEnabled ? 'Đăng nhập Forge' : 'Đăng nhập private team'}</h1>
        <p className="login-sub">Session và workspace được tách theo tài khoản. Provider key chỉ nằm trên server.</p>
        {props.needsSetup && (
          <div className="login-setup" role="status">
            <b>Chưa có tài khoản nào.</b> Tạo admin đầu tiên bằng
            <code>python scripts/setup_auth.py</code>, hoặc cấu hình Google OAuth rồi đăng nhập Google.
            Public signup chỉ hoạt động sau khi có admin.
          </div>
        )}
        {error && <div className="login-error" role="alert">{error}</div>}
        {props.googleEnabled ? (
          <>
            <a className="google-login" href="/api/auth/google/start">
              <span aria-hidden="true">G</span> {registering ? 'Tiếp tục bằng Google' : 'Đăng nhập bằng Google'}
            </a>
            <div className="login-divider">hoặc email / mật khẩu</div>
          </>
        ) : (
          <div className="auth-unavailable" role="status">Google login chưa được admin cấu hình.</div>
        )}
        <form onSubmit={submit} className="login-form">
          {registering && (
            <label>Tên hiển thị <span className="optional">(tuỳ chọn)</span>
              <input type="text" autoComplete="name" maxLength={120}
                value={name} onChange={(e) => setName(e.target.value)} />
            </label>
          )}
          <label>Email
            <input type="email" autoComplete="username" required maxLength={254}
              value={email} onChange={(e) => setEmail(e.target.value)} autoFocus={!props.googleEnabled} />
          </label>
          <label>Mật khẩu{registering && <span className="optional"> (tối thiểu 16 ký tự)</span>}
            <input type="password" autoComplete={registering ? 'new-password' : 'current-password'}
              required minLength={registering ? 16 : undefined} maxLength={512}
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {registering && (
            <label>Xác nhận mật khẩu
              <input type="password" autoComplete="new-password" required minLength={16} maxLength={512}
                value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </label>
          )}
          <button className="btn-primary login-submit"
            disabled={busy || !email.trim() || !password || (registering && !confirm)}>
            {busy ? 'Đang xử lý…' : registering ? 'Đăng ký và đăng nhập' : 'Đăng nhập'}
          </button>
        </form>
        {!props.needsSetup && (
          <div className="login-switch">
            {registering ? (
              <>Đã có tài khoản? <button type="button" onClick={() => switchMode('login')}>Đăng nhập</button></>
            ) : props.registrationEnabled ? (
              <>Chưa có tài khoản? <button type="button" onClick={() => switchMode('register')}>Đăng ký</button></>
            ) : (
              <span>Chưa có tài khoản? Liên hệ admin để được mời.</span>
            )}
          </div>
        )}
        <small className="login-foot">Cookie HttpOnly · phiên 8 giờ · CSRF cho mọi thay đổi. Google login không cấp quyền Gmail.</small>
      </section>
    </main>
  )
}
