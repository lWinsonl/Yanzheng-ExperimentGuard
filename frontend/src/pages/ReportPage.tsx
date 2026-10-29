import { useEffect, useState } from 'react'
import type { Finding, Followup, ReviewReport } from '../types'
import { CATEGORY_LABELS, LEVEL_LABELS } from '../types'
import { generateFollowups, runReview } from '../api'
import { FindingCard } from '../components/FindingCard'
import { DeepReviewPanel } from '../components/DeepReviewPanel'
import { TeachingCaseView } from '../components/TeachingCaseView'
import { LoadingDots } from '../components/LoadingDots'

interface Props {
  sessionId: string
  title: string
  claimTexts: Record<string, string>
  onNext: () => void
  onBack: () => void
}

/** 第四步:审查报告。发现按严重度分组,每条均可回溯原文。
 * 信息不足时自动展开追问;底部给教学案例训练实验设计能力。
 */
export function ReportPage({ sessionId, title, claimTexts, onNext, onBack }: Props) {
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

  // 首次进入报告页时自动运行审查(已有报告时不重复运行)
  useEffect(() => {
    if (report) return
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

  /** 导出审查报告为 Markdown 文件 */
  function exportMarkdown() {
    if (!report) return
    const lines: string[] = []
    lines.push(`# 审查报告${title ? ':' + title : ''}`)
    lines.push('')
    lines.push(`- 生成时间:${new Date(report.created_at).toLocaleString('zh-CN')}`)
    lines.push(`- 可用事实:${report.usable_fact_count}`)
    lines.push(`- 未确认/校验失败跳过:${report.skipped_fact_count}`)
    lines.push(`- 发现总计:${report.findings.length}`)
    if (followups.length > 0) {
      lines.push('')
      lines.push('## 智能体追问(待补充信息)')
      followups.forEach((f) => {
        lines.push(`- **${f.question}**`)
        if (f.what_to_provide) lines.push(`  - 请提供:${f.what_to_provide}`)
      })
    }
    for (const level of order) {
      const findings = grouped[level] ?? []
      if (findings.length === 0) continue
      lines.push('')
      lines.push(`## ${LEVEL_LABELS[level]}(${findings.length})`)
      lines.push('')
      findings.forEach((f, i) => {
        lines.push(`### ${i + 1}. ${f.title}`)
        lines.push('')
        lines.push(`- **规则**:${f.rule_id}`)
        if (f.claim_ids.length > 0) {
          const claims = f.claim_ids.map((cid) => claimTexts[cid] ?? cid).join('; ')
          lines.push(`- **涉及主张**:${claims}`)
        }
        if (f.evidence.length > 0) {
          lines.push(`- **依据**:`)
          f.evidence.forEach((e) => {
            lines.push(`  - [${CATEGORY_LABELS[e.category] ?? e.category}] ${e.value}`)
            if (e.source?.snippet) lines.push(`    > "${e.source.snippet}"`)
          })
        }
        if (f.missing_evidence.length > 0) {
          lines.push(`- **缺少证据**:${f.missing_evidence.join('; ')}`)
        }
        lines.push(`- **建议**:${f.suggestion}`)
        lines.push(`- **推理**:${f.reasoning}`)
        lines.push('')
      })
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `审查报告-${title || sessionId}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="page">
      <h2>第四步:审查报告</h2>
      <p className="muted">
        以下发现全部基于你已确认的事实,每条依据都可点击查看原文上下文。
        资源不足时,可选择收窄结论而非一律重做实验。
      </p>

      {error && <div className="error">{error}</div>}
      {busy && <LoadingDots text="正在运行学科规则审查" />}

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
        <button onClick={exportMarkdown} disabled={!report}>
          导出 Markdown
        </button>
        <button className="primary" onClick={onNext} disabled={!report}>
          下一步:修改后复查
        </button>
      </div>
    </div>
  )
}