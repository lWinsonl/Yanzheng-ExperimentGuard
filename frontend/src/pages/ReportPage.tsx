import { useEffect, useState } from 'react'
import type { Finding, Followup, ReviewReport } from '../types'
import { LEVEL_LABELS } from '../types'
import { generateFollowups, runReview } from '../api'
import { FindingCard } from '../components/FindingCard'
import { DeepReviewPanel } from '../components/DeepReviewPanel'
import { TeachingCaseView } from '../components/TeachingCaseView'

interface Props {
  sessionId: string
  claimTexts: Record<string, string>
  onNext: () => void
  onBack: () => void
}

/** 第四步:审查报告。发现按严重度分组,每条均可回溯原文。
 * 信息不足时自动展开追问;底部给教学案例训练实验设计能力。
 */
export function ReportPage({ sessionId, claimTexts, onNext, onBack }: Props) {
  const [report, setReport] = useState<ReviewReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [followups, setFollowups] = useState<Followup[]>([])

  async function run() {
    setBusy(true)
    setError('')
    try {
      setReport(await runReview(sessionId))
    } catch (e) {
      setError(e instanceof Error ? e.message : '审查失败')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    run()
  }, [])

  /** 报告生成后,如果有信息不足的发现,自动生成追问 */
  useEffect(() => {
    if (!report) return
    const hasInsufficient = report.findings.some((f) => f.level === 'insufficient')
    if (hasInsufficient) {
      generateFollowups(sessionId)
        .then((res) => setFollowups(res.followups ?? []))
        .catch(() => {})
    } else {
      setFollowups([])
    }
  }, [report])

  const order: Finding['level'][] = ['contradiction', 'risk', 'insufficient']
  const grouped = (report?.findings ?? []).reduce<Record<string, Finding[]>>((acc, f) => {
    ;(acc[f.level] ??= []).push(f)
    return acc
  }, {})

  return (
    <div className="page">
      <h2>第四步:审查报告</h2>
      <p className="muted">
        以下发现全部基于你已确认的事实,每条依据都可点击查看原文上下文。
        资源不足时,可选择收窄结论而非一律重做实验。
      </p>

      {error && <div className="error">{error}</div>}
      {busy && <div className="muted">审查运行中…</div>}

      {report && (
        <>
          <div className="report-stats">
            <span>可用事实:{report.usable_fact_count}</span>
            <span>未确认/校验失败跳过:{report.skipped_fact_count}</span>
            <span>
              发现总计:{report.findings.length}(
              {order
                .map((lv) => `${LEVEL_LABELS[lv]} ${(grouped[lv] ?? []).length}`)
                .join(' / ')}
              )
            </span>
          </div>

          {report.findings.length === 0 && (
            <div className="success">
              未发现证据问题。你的主张、计划与执行在已审查维度上一致。
              仍建议补充设备编号交集等直接证据以进一步确认。
            </div>
          )}

          {order.map((level) =>
            (grouped[level] ?? []).length > 0 ? (
              <div key={level} className="finding-group">
                <h3 className={`group-${level}`}>{LEVEL_LABELS[level]}</h3>
                {(grouped[level] ?? []).map((f) => (
                  <FindingCard
                    key={f.finding_id}
                    sessionId={sessionId}
                    finding={f}
                    claimTexts={claimTexts}
                  />
                ))}
              </div>
            ) : null,
          )}

          {/* 智能体追问:信息不足时自动展开 */}
          {followups.length > 0 && (
            <div className="followup-panel">
              <div className="agent-section-header">
                <span>🤖 智能体追问:请补充以下信息</span>
              </div>
              {followups.map((f, i) => (
                <div key={i} className="agent-item followup-item">
                  <div className="followup-question">❓ {f.question}</div>
                  {f.what_to_provide && (
                    <div className="muted">请提供:{f.what_to_provide}</div>
                  )}
                  {f.why_needed && (
                    <div className="muted">为什么需要:{f.why_needed}</div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* 模型复核:规则无法覆盖的复杂上下文 */}
          <DeepReviewPanel sessionId={sessionId} />

          {/* 教学小案例:训练实验设计能力 */}
          <div className="teaching-section">
            <h3>训练实验设计能力</h3>
            <p className="muted">
              看完报告后,试着自己判断一个新案例的实验漏洞——
              这比只看系统找出的漏洞更能训练你的实验设计能力。
            </p>
            <TeachingCaseView sessionId={sessionId} />
          </div>
        </>
      )}

      <div className="page-actions">
        <button onClick={onBack}>上一步</button>
        <button onClick={() => run()} disabled={busy}>
          重新审查
        </button>
        <button className="primary" onClick={onNext} disabled={!report}>
          下一步:修改后复查
        </button>
      </div>
    </div>
  )
}