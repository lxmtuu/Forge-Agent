import React, { useState } from 'react'
import { api } from '../api'
import type { AuthUser } from '../api'
import { useI18n } from '../i18n'

const OAUTH_ERRORS: Record<string, [string, string]> = {
  google_denied: ['Bạn đã huỷ đăng nhập Google.', 'Google sign-in was cancelled.'],
  google_state: ['Phiên đăng nhập Google không hợp lệ hoặc đã hết hạn.', 'The Google sign-in session is invalid or has expired.'],
  google_replay: ['Luồng đăng nhập Google đã được dùng. Hãy bắt đầu lại.', 'This Google sign-in flow has already been used. Please start again.'],
  google_invalid: ['Không xác minh được danh tính Google.', 'Google identity could not be verified.'],
  not_invited: ['Email chưa được admin mời, hoặc tự đăng ký đang tắt.', 'This email has not been invited by an admin, or public registration is disabled.'],
  disabled: ['Tài khoản đang bị vô hiệu hoá.', 'This account is disabled.'],
}

// Auth API errors include an HTTP prefix; show a concise localized message for known cases.
const AUTH_ERROR_EN: Record<string, string> = {
  'Email hoặc mật khẩu không đúng': 'Incorrect email or password',
  'Email không hợp lệ': 'Invalid email address',
  'Email đã tồn tại': 'An account with this email already exists',
  'Mật khẩu phải từ 16 đến 512 ký tự': 'Password must be between 16 and 512 characters',
  'Tên không hợp lệ': 'Invalid display name',
  'Cần bootstrap admin trước khi mở đăng ký': 'Create an admin account before enabling registration',
  'Tự đăng ký đang tắt — liên hệ admin': 'Public registration is disabled — contact an admin',
  'Quá nhiều lượt đăng ký — thử lại sau': 'Too many registration attempts — try again later',
  'Quá nhiều lần đăng nhập — thử lại sau': 'Too many sign-in attempts — try again later',
  'Tài khoản đang bị vô hiệu hoá': 'This account is disabled',
}

export function LoginScreen(props: {
  googleEnabled: boolean
  registrationEnabled: boolean
  needsSetup: boolean
  onLoggedIn: (user: AuthUser) => void
}) {
  const { t, language, setLanguage } = useI18n()
  const params = new URLSearchParams(window.location.search)
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(() => {
    const entry = OAUTH_ERRORS[params.get('error') ?? '']
    return entry ? t(...entry) : null
  })
  const registering = mode === 'register'

  function switchMode(next: 'login' | 'register') {
    setMode(next); setError(null); setPassword(''); setConfirm('')
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    if (registering && password.length < 16) {
      setError(t('Mật khẩu phải có ít nhất 16 ký tự.', 'Password must be at least 16 characters long.'))
      return
    }
    if (registering && password !== confirm) {
      setError(t('Mật khẩu xác nhận không khớp.', 'The password confirmation does not match.'))
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
      const message = (err as Error).message
      const translated = language === 'en'
        ? Object.entries(AUTH_ERROR_EN).find(([vi]) => message.includes(vi))?.[1]
        : undefined
      setError(translated ?? message)
    } finally { setBusy(false) }
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-brand-row">
          <div className="login-brand"><span className="login-bolt">⚡</span> Forge <em>agent</em></div>
          <div className="login-language" role="group" aria-label={t('Ngôn ngữ giao diện', 'Interface language')}>
            <button type="button" className={language === 'vi' ? 'on' : ''} aria-pressed={language === 'vi'} onClick={() => setLanguage('vi')}>VI</button>
            <button type="button" className={language === 'en' ? 'on' : ''} aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>EN</button>
          </div>
        </div>
        <h1 id="login-title">{registering ? t('Tạo tài khoản member', 'Create a member account') : props.registrationEnabled ? t('Đăng nhập Forge', 'Sign in to Forge') : t('Đăng nhập private team', 'Private team sign in')}</h1>
        <p className="login-sub">{t('Session và workspace được tách theo tài khoản. Provider key chỉ nằm trên server.', 'Sessions and workspaces are isolated by account. Provider keys remain on the server.')}</p>
        {props.needsSetup && (
          <div className="login-setup" role="status">
            <b>{t('Chưa có tài khoản nào.', 'No accounts yet.')}</b> {t('Tạo admin đầu tiên bằng', 'Create the first admin with')}
            <code>python scripts/setup_auth.py</code>, {t('hoặc cấu hình Google OAuth rồi đăng nhập Google.', 'or configure Google OAuth and sign in with Google.')}
            {' '}{t('Public signup chỉ hoạt động sau khi có admin.', 'Public signup becomes available after an admin exists.')}
          </div>
        )}
        {error && <div className="login-error" role="alert">{error}</div>}
        {props.googleEnabled ? (
          <>
            <a className="google-login" href="/api/auth/google/start">
              <span aria-hidden="true">G</span> {registering ? t('Tiếp tục bằng Google', 'Continue with Google') : t('Đăng nhập bằng Google', 'Sign in with Google')}
            </a>
            <div className="login-divider">{t('hoặc email / mật khẩu', 'or email / password')}</div>
          </>
        ) : (
          <div className="auth-unavailable" role="status">{t('Google login chưa được admin cấu hình.', 'Google sign-in has not been configured by an admin.')}</div>
        )}
        <form onSubmit={submit} className="login-form">
          {registering && (
            <label>{t('Tên hiển thị', 'Display name')} <span className="optional">{t('(tuỳ chọn)', '(optional)')}</span>
              <input type="text" autoComplete="name" maxLength={120}
                value={name} onChange={(e) => setName(e.target.value)} />
            </label>
          )}
          <label>Email
            <input type="email" autoComplete="username" required maxLength={254}
              value={email} onChange={(e) => setEmail(e.target.value)} autoFocus={!props.googleEnabled} />
          </label>
          <label>{t('Mật khẩu', 'Password')}{registering && <span className="optional"> {t('(tối thiểu 16 ký tự)', '(minimum 16 characters)')}</span>}
            <input type="password" autoComplete={registering ? 'new-password' : 'current-password'}
              required minLength={registering ? 16 : undefined} maxLength={512}
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {registering && (
            <label>{t('Xác nhận mật khẩu', 'Confirm password')}
              <input type="password" autoComplete="new-password" required minLength={16} maxLength={512}
                value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </label>
          )}
          <button className="btn-primary login-submit"
            disabled={busy || !email.trim() || !password || (registering && !confirm)}>
            {busy ? t('Đang xử lý…', 'Please wait…') : registering ? t('Đăng ký và đăng nhập', 'Create account and sign in') : t('Đăng nhập', 'Sign in')}
          </button>
        </form>
        {!props.needsSetup && (
          <div className="login-switch">
            {registering ? (
              <>{t('Đã có tài khoản?', 'Already have an account?')} <button type="button" onClick={() => switchMode('login')}>{t('Đăng nhập', 'Sign in')}</button></>
            ) : props.registrationEnabled ? (
              <>{t('Chưa có tài khoản?', 'Need an account?')} <button type="button" onClick={() => switchMode('register')}>{t('Đăng ký', 'Register')}</button></>
            ) : (
              <span>{t('Chưa có tài khoản? Liên hệ admin để được mời.', 'Need an account? Contact an admin for an invitation.')}</span>
            )}
          </div>
        )}
        <small className="login-foot">{t('Cookie HttpOnly · phiên 8 giờ · CSRF cho mọi thay đổi. Google login không cấp quyền Gmail.', 'HttpOnly cookies · 8-hour sessions · CSRF on every mutation. Google sign-in does not grant Gmail access.')}</small>
      </section>
    </main>
  )
}
