import { useEffect, useRef, useState } from 'react'
import type { AgentStatus, ReviewSession } from './types'
import { getAgentStatus, getSession } from './api'
import { SetupPage } from './pages/SetupPage'
import { UploadPage } from './pages/UploadPage'
import { FactConfirmPage } from './pages/FactConfirmPage'
import { ReportPage } from './pages/ReportPage'
import { RecheckPage } from './pages/RecheckPage'
import { SessionHistory } from './components/SessionHistory'
import { LoginPage } from './pages/LoginPage'

type Step = 'setup' | 'upload' | 'facts' | 'report' | 'recheck'

const STEPS: { key: Step; label: string }[] = [
  { key: 'setup', label: '确定范围' },
  { key: 'upload', label: '收集材料' },
  { key: 'facts', label: '确认事实' },
  { key: 'report', label: '审查报告' },
  { key: 'recheck', label: '修改复查' },
]

const SESSION_KEY = 'yanzheng_session'
const STEP_KEY = 'yanzheng_step'

function loadSession(): ReviewSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY)
    const parsed = raw ? JSON.parse(raw) as ReviewSession : null
    return parsed && typeof parsed.session_id === 'string' && Array.isArray(parsed.claims)
      && parsed.claims.every((c) => typeof c.claim_id === 'string' && typeof c.text === 'string') ? parsed : null
  } catch {
    return null
  }
}

function loadStep(): Step {
  try {
    const raw = localStorage.getItem(STEP_KEY)
    return STEPS.some((step) => step.key === raw) ? raw as Step : 'setup'
  } catch { return 'setup' }
}

function Workspace() {
  const [step, setStep] = useState<Step>(() => loadSession() ? loadStep() : 'setup')
  const [session, setSession] = useState<ReviewSession | null>(loadSession)
  const [showHistory, setShowHistory] = useState(false)
  const sessionIntent = useRef(0)
  const [agentResult, setAgentResult] = useState<{ sessionId: string; value: AgentStatus } | null>(null)
  const sessionId = session?.session_id
  const agentStatus = agentResult?.sessionId === sessionId ? agentResult?.value : null

  // 持久化:session / step 变化时写入 localStorage
  useEffect(() => {
    try {
      if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session))
      else localStorage.removeItem(SESSION_KEY)
    } catch { /* private mode may disable persistence; current in-memory session remains usable */ }
  }, [session])
  useEffect(() => {
    try { localStorage.setItem(STEP_KEY, step) } catch { /* keep current session usable */ }
  }, [step])

  // 恢复时校验会话在后端是否仍存在,不存在则清空
  useEffect(() => {
    const restored = loadSession()
    if (!restored) return
    const intent = sessionIntent.current
    let active = true
    getSession(restored.session_id).then(value => {
      if (active && sessionIntent.current === intent) setSession(value)
    }).catch(() => {
      if (active && sessionIntent.current === intent) {
        setSession(null)
        setStep('setup')
      }
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!sessionId) return
    let active = true
    getAgentStatus(sessionId).then((value) => { if (active) setAgentResult({ sessionId, value }) }).catch(() => {})
    return () => { active = false }
  }, [sessionId])

  function startNew() {
    sessionIntent.current++
    setSession(null)
    setStep('setup')
  }

  const claimTexts: Record<string, string> = {}
  if (session) {
    for (const c of session.claims) {
      claimTexts[c.claim_id] = c.text
    }
  }

  function go(target: Step) {
    // 未创建会话时只能停留在 setup
    if (!session && target !== 'setup') return
    setStep(target)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>研证</h1>
        <p className="tagline">
          审查你的研究结论能否被实验支持 —— 主张、计划与执行逐项对照
        </p>
        <div className="header-actions">
        {agentStatus && (
          <span
            className={`mode-badge ${agentStatus.mode}`}
            title={agentStatus.note}
          >
            {agentStatus.mode === 'llm' ? '模型模式' : '启发式模式'}
          </span>
        )}
        <button onClick={() => setShowHistory(true)}>历史会话</button>
        {session && (
          <button className="new-session-btn" onClick={startNew}>
            新建审查
          </button>
        )}
        </div>
      </header>

      {showHistory && <SessionHistory currentSessionId={sessionId}
        onClose={() => setShowHistory(false)}
        onOpen={value => {
          sessionIntent.current++
          setSession(value)
          setStep('upload')
          setShowHistory(false)
        }} />}

      <nav className="stepper">
        {STEPS.map((s, i) => {
          const active = step === s.key
          const reachable = session || s.key === 'setup'
          return (
            <button
              key={s.key}
              aria-label={`第${i + 1}步：${s.label}`}
              aria-current={active ? 'step' : undefined}
              disabled={!reachable}
              className={`step ${active ? 'active' : ''} ${reachable ? '' : 'disabled'}`}
              onClick={() => reachable && go(s.key)}
            >
              <span className="step-num">{i + 1}</span>
              <span className="step-label">{s.label}</span>
            </button>
          )
        })}
      </nav>

      <main className="app-main">
        {step === 'setup' && (
          <SetupPage
            onCreated={(s) => { sessionIntent.current++; setSession(s) }}
            onNext={() => setStep('upload')}
          />
        )}
        {step === 'upload' && session && (
          <UploadPage key={session.session_id}
            sessionId={session.session_id}
            onBack={() => setStep('setup')}
            onNext={() => setStep('facts')}
          />
        )}
        {step === 'facts' && session && (
          <FactConfirmPage key={session.session_id}
            sessionId={session.session_id}
            onBack={() => setStep('upload')}
            onNext={() => setStep('report')}
          />
        )}
        {step === 'report' && session && (
          <ReportPage key={session.session_id}
            sessionId={session.session_id}
            title={session.title}
            claimTexts={claimTexts}
            onBack={() => setStep('facts')}
            onNext={() => setStep('recheck')}
          />
        )}
        {step === 'recheck' && session && (
          <RecheckPage key={session.session_id}
            sessionId={session.session_id}
            onBack={() => setStep('report')}
            onAddMaterial={() => setStep('upload')}
          />
        )}
      </main>

      <footer className="app-footer muted">
        处理链:解析文件 → 提取带出处的事实 → 用户确认 → 运行学科规则 → 生成报告 → 修改复查
      </footer>
    </div>
  )
}

type AccessState = { login_required: boolean; authenticated: boolean }

export default function App() {
  const [access, setAccess] = useState<AccessState | null>(null)
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true
    fetch('/api/auth/status').then(async response => {
      if (!response.ok) throw new Error('无法确认登录状态')
      return response.json() as Promise<AccessState>
    }).then(value => { if (active) setAccess(value) })
      .catch(() => { if (active) setAccess({ login_required: true, authenticated: false }) })
    return () => { active = false }
  }, [refresh])

  if (!access) return <main className="login-shell"><p className="muted">正在连接研证…</p></main>
  if (access.login_required && !access.authenticated) {
    return <LoginPage onLoggedIn={() => setRefresh(value => value + 1)} />
  }
  return <Workspace />
}
