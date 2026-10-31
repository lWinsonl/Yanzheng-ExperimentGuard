import { useEffect, useState } from 'react'
import type { AgentStatus, ReviewSession } from './types'
import { getAgentStatus, getSession } from './api'
import { SetupPage } from './pages/SetupPage'
import { UploadPage } from './pages/UploadPage'
import { FactConfirmPage } from './pages/FactConfirmPage'
import { ReportPage } from './pages/ReportPage'
import { RecheckPage } from './pages/RecheckPage'

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
    return raw ? (JSON.parse(raw) as ReviewSession) : null
  } catch {
    return null
  }
}

function loadStep(): Step {
  const raw = localStorage.getItem(STEP_KEY)
  return (raw as Step) || 'setup'
}

export default function App() {
  const [step, setStep] = useState<Step>(loadStep)
  const [session, setSession] = useState<ReviewSession | null>(loadSession)
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null)

  // 持久化:session / step 变化时写入 localStorage
  useEffect(() => {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session))
    else localStorage.removeItem(SESSION_KEY)
  }, [session])
  useEffect(() => {
    localStorage.setItem(STEP_KEY, step)
  }, [step])

  // 恢复时校验会话在后端是否仍存在,不存在则清空
  useEffect(() => {
    const restored = loadSession()
    if (!restored) return
    getSession(restored.session_id).then(setSession).catch(() => {
      setSession(null)
      setStep('setup')
    })
  }, [])

  // 会话变化时获取智能体运行模式(模型/启发式)
  useEffect(() => {
    if (!session) {
      setAgentStatus(null)
      return
    }
    getAgentStatus(session.session_id).then(setAgentStatus).catch(() => {})
  }, [session?.session_id])

  function startNew() {
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
        {agentStatus && (
          <span
            className={`mode-badge ${agentStatus.mode}`}
            title={agentStatus.note}
          >
            {agentStatus.mode === 'llm' ? '模型模式' : '启发式模式'}
          </span>
        )}
        {session && (
          <button className="new-session-btn" onClick={startNew}>
            新建审查
          </button>
        )}
      </header>

      <nav className="stepper">
        {STEPS.map((s, i) => {
          const active = step === s.key
          const reachable = session || s.key === 'setup'
          return (
            <button
              key={s.key}
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
            onCreated={(s) => setSession(s)}
            onNext={() => setStep('upload')}
            onOpenSession={(s) => {
              setSession(s)
              setStep('upload')
            }}
          />
        )}
        {step === 'upload' && session && (
          <UploadPage
            sessionId={session.session_id}
            onBack={() => setStep('setup')}
            onNext={() => setStep('facts')}
          />
        )}
        {step === 'facts' && session && (
          <FactConfirmPage
            sessionId={session.session_id}
            onBack={() => setStep('upload')}
            onNext={() => setStep('report')}
          />
        )}
        {step === 'report' && session && (
          <ReportPage
            sessionId={session.session_id}
            title={session.title}
            claimTexts={claimTexts}
            onBack={() => setStep('facts')}
            onNext={() => setStep('recheck')}
          />
        )}
        {step === 'recheck' && session && (
          <RecheckPage
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