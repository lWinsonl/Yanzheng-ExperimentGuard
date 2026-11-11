import { useState } from 'react'

type Props = { onLoggedIn: () => void }

export function LoginPage({ onLoggedIn }: Props) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function enter() {
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/auth/enter', { method: 'POST' })
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
    <section className="login-card" aria-labelledby="login-title">
      <div className="login-mark">研</div>
      <p className="login-eyebrow">RESEARCH EVIDENCE REVIEW</p>
      <h1 id="login-title">研证</h1>
      <p className="login-description">审查研究结论能否被实验材料支持</p>
      <p className="login-public-note">评委公开体验入口，无需输入账号和密码。</p>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary login-submit" type="button" onClick={enter} disabled={busy}>
        {busy ? '正在进入…' : '进入评审演示'}
      </button>
      <p className="login-footnote">进入后可直接体验完整审查流程</p>
    </section>
  </main>
}
