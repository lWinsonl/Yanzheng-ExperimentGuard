import { useEffect, useState } from 'react'
import type { DirectionAnalysis, ExperimentType, ReviewSession } from '../types'
import { analyzeDirection, createSession, listSessions } from '../api'
import { DEMO_CLAIMS, DEMO_TITLE } from '../demo-data'
import { LoadingDots } from '../components/LoadingDots'

interface Props {
  onCreated: (session: ReviewSession) => void
  onNext: () => void
  onOpenSession: (session: ReviewSession) => void
}

const EXP_TYPE_LABEL: Record<string, string> = {
  data_model: '数据与模型实验',
  algorithm_system: '算法与系统性能实验',
}

/** 第一步:确定审查范围——实验类型 + 研究主张。
 * 创建会话后自动运行方向审查,告诉用户"你的主张需要什么实验设计",
 * 引导用户上传对的材料。
 */
export function SetupPage({ onCreated, onNext, onOpenSession }: Props) {
  const [title, setTitle] = useState('')
  const [expType, setExpType] = useState<ExperimentType>('data_model')
  const [claimsText, setClaimsText] = useState(
    '模型 A 比基线 B 更能预测新设备的故障,且更稳定。',
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [session, setSession] = useState<ReviewSession | null>(null)
  const [direction, setDirection] = useState<DirectionAnalysis | null>(null)
  const [dirBusy, setDirBusy] = useState(false)
  const [history, setHistory] = useState<ReviewSession[]>([])
  const [showHistory, setShowHistory] = useState(false)

  useEffect(() => {
    listSessions()
      .then((list) => setHistory(list.filter((s) => s.title).slice(0, 10)))
      .catch(() => {})
  }, [])

  function loadDemo() {
    setTitle(DEMO_TITLE)
    setExpType('data_model')
    setClaimsText(DEMO_CLAIMS)
    setError('')
  }

  async function submit() {
    const claims = claimsText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    if (claims.length === 0) {
      setError('请至少写出一条研究主张')
      return
    }
    setBusy(true)
    setError('')
    try {
      const s = await createSession(title, expType, claims)
      setSession(s)
      onCreated(s)
      // 自动运行方向审查
      setDirBusy(true)
      try {
        setDirection(await analyzeDirection(s.session_id))
      } catch {
        /* 方向审查失败不阻断流程 */
      } finally {
        setDirBusy(false)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
    } finally {
      setBusy(false)
    }
  }

  const clarityLabel: Record<string, string> = {
    clear: '清晰可检验',
    vague: '表述模糊',
    untestable: '不可检验',
    unknown: '未知',
  }

  return (
    <div className="page">
      <h2>第一步:确定审查范围</h2>
      <p className="muted">
        写出你的研究主张。系统将逐项对照你的主张、实验计划和实际执行,
        指出有证据的问题。
      </p>

      <div className="form-group">
        <label>审查标题</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="例如:设备故障预测模型对比实验"
          disabled={!!session}
        />
      </div>

      <div className="form-group">
        <label>实验类型</label>
        <select
          value={expType}
          onChange={(e) => setExpType(e.target.value as ExperimentType)}
          disabled={!!session}
        >
          <option value="data_model">数据与模型实验</option>
          <option value="algorithm_system">算法与系统性能实验</option>
        </select>
      </div>

      <div className="form-group">
        <label>研究主张(每行一条)</label>
        <textarea
          rows={4}
          value={claimsText}
          onChange={(e) => setClaimsText(e.target.value)}
          placeholder="例如:模型 A 比基线 B 更能预测新设备的故障。"
          disabled={!!session}
        />
      </div>

      {error && <div className="error">{error}</div>}

      {!session && (
        <div className="page-actions">
          <button className="primary" disabled={busy} onClick={submit}>
            {busy ? '创建中…' : '创建审查会话'}
          </button>
          <button disabled={busy} onClick={loadDemo} title="一键填入演示数据">
            加载示例
          </button>
        </div>
      )}

      {/* 历史会话:默认折叠,点击按钮展开选择 */}
      {!session && history.length > 0 && (
        <div className="session-history">
          {showHistory ? (
            <>
              <div className="agent-section-header">
                <h4>历史审查会话</h4>
                <button onClick={() => setShowHistory(false)}>收起</button>
              </div>
              {history.map((s) => (
                <div
                  key={s.session_id}
                  className="session-history-item"
                  onClick={() => onOpenSession(s)}
                  title="点击继续此审查"
                >
                  <span className="session-history-title">
                    {s.title || '(无标题)'}
                  </span>
                  <span className="session-history-meta">
                    {EXP_TYPE_LABEL[s.experiment_type] ?? s.experiment_type}
                    {' · '}
                    {s.claims.length} 条主张
                    {' · '}
                    {new Date(s.created_at).toLocaleDateString('zh-CN')}
                  </span>
                </div>
              ))}
            </>
          ) : (
            <button onClick={() => setShowHistory(true)}>
              查看历史审查会话({history.length})
            </button>
          )}
        </div>
      )}

      {/* 方向审查:创建后自动展示,引导用户上传对的材料 */}
      {session && (
        <div className="direction-result">
          <div className="agent-section-header">
            <span>🤖 方向审查:你的主张需要什么实验设计</span>
            {direction?.source === 'llm' && (
              <span className="agent-source">模型分析</span>
            )}
          </div>

          {dirBusy && <LoadingDots text="正在分析你的研究方向" />}

          {direction && !dirBusy && (
            <div className="agent-result">
              <div className="agent-tag-row">
                <span className={`agent-tag clarity-${direction.claim_clarity}`}>
                  主张{clarityLabel[direction.claim_clarity] ?? direction.claim_clarity}
                </span>
              </div>
              {direction.clarity_note && (
                <div className="muted">{direction.clarity_note}</div>
              )}
              {direction.design_requirements.length > 0 && (
                <div className="agent-subsection">
                  <div className="section-label">上传材料时请确保覆盖以下要求</div>
                  {direction.design_requirements.map((r, i) => (
                    <div key={i} className="agent-item">
                      <div className="agent-item-title">{r.requirement}</div>
                      <div className="muted">原因:{r.reason}</div>
                    </div>
                  ))}
                </div>
              )}
              {direction.direction_issues.length > 0 && (
                <div className="agent-subsection">
                  <div className="section-label">方向性问题</div>
                  {direction.direction_issues.map((iss, i) => (
                    <div key={i} className="agent-item">
                      {iss.issue}
                      <div className="muted">{iss.explanation}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <button className="primary" onClick={onNext}>
            下一步:上传材料
          </button>
        </div>
      )}
    </div>
  )
}