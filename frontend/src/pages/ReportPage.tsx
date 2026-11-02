import { useEffect, useState } from 'react'
import type { ClaimGraph, DeepReviewResult, DeepReviewStatus, Finding, Followup, ReviewReport } from '../types'
import {
  ASPECT_LABELS,
  CATEGORY_LABELS,
  COUNTER_STATUS_LABELS,
  DIRECTION_LABELS,
  LEVEL_LABELS,
  RELATION_LABELS,
} from '../types'
import { generateFollowups, getLatestReport, runReview } from '../api'
import { FindingCard } from '../components/FindingCard'
import { DeepReviewPanel } from '../components/DeepReviewPanel'
import { ClaimGraphPanel } from '../components/ClaimGraphPanel'
import { FollowupPanel } from '../components/FollowupPanel'
import { VersionDiffPanel } from '../components/VersionDiffPanel'
import { MigrationQuiz } from '../components/MigrationQuiz'
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
  const [deepResult, setDeepResult] = useState<DeepReviewResult | null>(null)
  const [graph, setGraph] = useState<ClaimGraph | null>(null)

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

  /** 追问回答后刷新报告(后端已重算审查,前端只取最新) */
  async function refreshReport() {
    try {
      setReport(await getLatestReport(sessionId))
    } catch {
      /* 保持旧报告 */
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
    if (deepResult) {
      lines.push('')
      lines.push('## 模型复核(详细修改建议)')
      const statusLabel: Record<DeepReviewStatus, string> = {
        ok: '调用成功',
        ok_no_findings: '调用成功,未发现需要补充的问题',
        llm_unavailable: '未接入模型,复核未执行',
        llm_call_failed: '模型调用失败,复核未完成',
        llm_parse_failed: '模型输出解析失败,复核未完成',
      }
      lines.push(`- **状态**:${statusLabel[deepResult.status] ?? deepResult.status}`)
      if (deepResult.message) lines.push(`- **说明**:${deepResult.message}`)
      if (deepResult.coverage.length > 0) {
        lines.push('- **复核范围**:')
        deepResult.coverage.forEach((c) => {
          if (c.checked_chars === 0) {
            lines.push(`  - ${c.filename}:未检查(超出总量限制,共 ${c.total_chars} 字符)`)
          } else if (c.truncated) {
            lines.push(`  - ${c.filename}:检查了前 ${c.checked_chars}/${c.total_chars} 字符,其余未检查`)
          } else {
            lines.push(`  - ${c.filename}:已全量检查(${c.total_chars} 字符)`)
          }
        })
      }
      deepResult.findings.forEach((f, i) => {
        lines.push('')
        lines.push(`### ${i + 1}. ${f.title}`)
        lines.push('')
        lines.push(`- **级别**:${LEVEL_LABELS[f.level] ?? f.level}`)
        if (f.reasoning) lines.push(`- **推理**:${f.reasoning}`)
        if (f.verified_quote) lines.push(`- **原文引用**:"${f.verified_quote}"`)
        if (f.material_filename) lines.push(`- **来源材料**:${f.material_filename}`)
        if (f.suggestion) lines.push(`- **建议**:${f.suggestion}`)
      })
    }
    if (graph) {
      lines.push('')
      lines.push('## 主张-证据图')
      const claimIdSet = [...new Set(graph.sub_claims.map((sc) => sc.claim_id))]
      claimIdSet.forEach((cid) => {
        const cText = claimTexts[cid] ?? cid
        const subs = graph.sub_claims.filter((sc) => sc.claim_id === cid && sc.status !== 'rejected')
        lines.push('')
        lines.push(`### 主张:${cText}`)
        subs.forEach((sc) => {
          lines.push('')
          lines.push(`#### [${ASPECT_LABELS[sc.test_aspect]}] ${sc.text}`)
          const edges = graph.edges.filter((e) => e.sub_claim_id === sc.sub_claim_id && e.status !== 'rejected')
          edges.forEach((e) => {
            const rel = e.corrected_relation ?? e.relation
            lines.push(`- **${RELATION_LABELS[rel]}**(${DIRECTION_LABELS[e.direction]}):${e.basis}`)
          })
          const check = graph.counter_checks.find((cc) => cc.sub_claim_id === sc.sub_claim_id)
          if (check) {
            lines.push(`- **反证检查**:${COUNTER_STATUS_LABELS[check.proof_status]}`)
            if (check.alternative_explanation) lines.push(`  - 替代解释:${check.alternative_explanation}`)
            if (check.missing_to_prove_absence.length > 0) {
              lines.push(`  - 升级为"证明不存在反证"还需:${check.missing_to_prove_absence.join('; ')}`)
            }
          }
        })
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

          {/* 主张-证据图:可校准的子主张-证据连接 */}
          <ClaimGraphPanel
            sessionId={sessionId}
            claimTexts={claimTexts}
            onGraphChange={setGraph}
          />

          {/* 主动追问:基于预期信息价值排序,回答后追踪发现变化 */}
          <FollowupPanel
            sessionId={sessionId}
            onAnswerRecorded={refreshReport}
          />

          {/* 模型复核:详细修改建议 + 规则盲区 */}
          <DeepReviewPanel sessionId={sessionId} onResultChange={setDeepResult} />

          {/* 版本差异复审:稳定身份配对 + 五态判定 + 修改理由对照 + 人工标签(P2) */}
          <VersionDiffPanel sessionId={sessionId} />

          {/* 学习迁移评估:不同情境同方法要点,评分看推理过程(P2) */}
          <MigrationQuiz sessionId={sessionId} />

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