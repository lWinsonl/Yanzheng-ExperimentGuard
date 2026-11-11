import { useState, type FormEvent } from 'react'

type Props = { demoUsername: string; demoPassword: string; onLoggedIn: () => void }

export function LoginPage({ demoUsername, demoPassword, onLoggedIn }: Props) {
  const [username, setUsername] = useState(demoUsername)
  const [password, setPassword] = useState(demoPassword)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function enter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!response.ok) {
        const result = await response.json().catch(() => ({}))
        throw new Error(result.detail || '暂时无法进入，请稍后重试。')
      }
      onLoggedIn()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '暂时无法进入，请稍后重试。')
    } finally { setBusy(false) }
  }

  return <main className="login-shell">
    <form className="login-card" aria-labelledby="login-title" onSubmit={enter}>
      <div className="login-mark">研</div>
      <p className="login-eyebrow">RESEARCH EVIDENCE REVIEW</p>
      <h1 id="login-title">研证</h1>
      <p className="login-description">审查研究结论能否被实验材料支持</p>
      <p className="login-public-note">已为您填好公开演示账号，点击登录即可体验。</p>
      <label htmlFor="demo-username">账号</label>
      <input id="demo-username" autoComplete="username" value={username}
        onChange={event => setUsername(event.target.value)} maxLength={128} required />
      <label htmlFor="demo-password">密码</label>
      <input id="demo-password" type="password" autoComplete="current-password" value={password}
        onChange={event => setPassword(event.target.value)} maxLength={256} required />
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary login-submit" type="submit" disabled={busy}>
        {busy ? '正在登录…' : '登录并进入'}
      </button>
      <p className="login-footnote">进入后可直接体验完整审查流程</p>
    </form>
  </main>
}
