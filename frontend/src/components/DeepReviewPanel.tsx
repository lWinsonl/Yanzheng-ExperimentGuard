import { useState } from 'react'
import type { DeepReviewResult, DeepReviewStatus, MaterialCoverage } from '../types'
import { LEVEL_COLORS, LEVEL_LABELS } from '../types'
import { deepReview } from '../api'
import { LoadingDots } from './LoadingDots'

interface Props {
  sessionId: string
  /** 复核完成时通知父组件(传完整结果,含状态与覆盖范围,用于导出报告等) */
  onResultChange?: (result: DeepReviewResult | null) => void
}

/** 状态 → 展示文案与样式类 */
const STATUS_DISPLAY: Record<DeepReviewStatus, { text: string; cls: string }> = {
  ok: { text: '', cls: '' },
  ok_no_findings: { text: '本次模型未补充新发现。已有程序问题仍需处理。', cls: 'muted' },
  llm_unavailable: {
    text: '未接入模型,此功能需要配置 LLM 密钥(当前运行在启发式模式)。',
    cls: 'warn',
  },
  llm_call_failed: {
    text: '模型复核未完成，程序核对结果仍可查看。请检查服务日志，确认是否超时、达到调用限额或配置有误。',
    cls: 'error',
  },
  llm_parse_failed: {
    text: '模型返回了内容但无法解析为结构化结果,本次复核未完成,请重试。',
    cls: 'error',
  },
  needs_evidence: {
    text: '模型输出没有通过本轮证据校验，未采用其中的修改操作。请先查看程序结果和待核实项。',
    cls: 'warn',
  },
}

/** 覆盖范围面板:告知用户模型实际检查了哪些材料、哪些内容因过长被截断 */
function CoveragePanel({ coverage }: { coverage: MaterialCoverage[] }) {
  if (coverage.length === 0) return null
  const hasTruncated = coverage.some((c) => c.truncated)
  return (
    <div className={`coverage-panel${hasTruncated ? ' has-truncated' : ''}`}>
      <div className="coverage-title">
        提供给模型的范围{hasTruncated ? '(只提供选中内容，其余未供模型阅读)' : ''}
      </div>
      {coverage.map((c) => (
        <div key={c.material_id} className={`coverage-item${c.truncated ? ' truncated' : ''}`}>
          <span className={`role-tag ${c.role}`}>
            {c.role === 'plan' ? '计划' : '执行'}
          </span>
          <span className="coverage-filename">{c.filename}</span>
          {c.checked_chars === 0 ? (
            <span className="coverage-note warn">未检查(超出总量限制)</span>
          ) : c.truncated ? (
            <span className="coverage-note warn">
              {c.selection_mode === 'selected_evidence' ? '提供了选中片段' : '提供了前段'} {c.checked_chars} / {c.total_chars} 字符
            </span>
          ) : (
            <span className="coverage-note ok">已提供全文({c.total_chars} 字符)</span>
          )}
        </div>
      ))}
    </div>
  )
}

/**
 * 模型复核面板:对规则发现的问题给出详细修复方案,并发现规则无法覆盖的复杂上下文。
 * 通过 status 区分:调用成功(有/无发现)、未接入模型、调用失败、解析失败。
 * 覆盖范围面板明示长文档截断情况,避免用户误以为已全量检查。
 */
export function DeepReviewPanel({ sessionId, onResultChange }: Props) {
  const [result, setResult] = useState<DeepReviewResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      const res = await deepReview(sessionId)
      setResult(res)
      onResultChange?.(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : '复核请求失败,请检查服务是否正常运行')
    } finally {
      setBusy(false)
    }
  }

  const findings = result?.findings ?? []
  const statusInfo = result ? STATUS_DISPLAY[result.status] : null

  return (
    <div className="deep-review-panel">
      <div className="agent-section-header">
        <span>模型复核与待验证建议</span>
        <button disabled={busy} onClick={run}>
          {busy ? '复核中…' : result ? '重新复核' : '运行模型复核'}
        </button>
      </div>
      {busy && <LoadingDots text="模型正在复核复杂上下文，请保持页面打开" />}
      {error && !busy && (
        <div className="error">复核请求失败:{error}</div>
      )}
      {result && !busy && statusInfo && statusInfo.text && (
        <div className={statusInfo.cls}>{statusInfo.text}</div>
      )}
      {result && !busy && result.coverage.length > 0 && (
        <CoveragePanel coverage={result.coverage} />
      )}
      {result && !busy && <p className="muted">{result.validation_note || '引用存在不代表推断正确；建议需用新记录验证。'}</p>}
      {!!result?.unverified?.length && !busy && <section className="warn" aria-label="未采纳的模型输出">
        <strong>这些输出未采纳修改操作</strong>
        {result.unverified.map((f, i) => <p key={i}>{f.title}：{f.reason}</p>)}
      </section>}
      {findings.map((f, i) => (
        <div
          key={i}
          className="finding-card deep-finding"
          style={{ borderLeftColor: LEVEL_COLORS[f.level] ?? '#5f6368' }}
        >
          <div className="finding-header">
            <span
              className="finding-level"
              style={{ background: LEVEL_COLORS[f.level] ?? '#5f6368' }}
            >
              {LEVEL_LABELS[f.level] ?? f.level}
            </span>
            <span className="finding-title">{f.title}</span>
            {f.evidence_verified && (
              <span className="verify-badge" title="来源由服务器按本轮证据编号绑定；推理仍需核对">
                ✓ 证据来源已绑定
              </span>
            )}
          </div>
          {f.reasoning && (
            <div className="finding-section">
              <div className="section-label">推理</div>
              <div className="finding-reasoning">{f.reasoning}</div>
            </div>
          )}
          {f.evidence?.length ? <div className="finding-section">
            <div className="section-label">依据</div>
            {f.evidence.map(e => <details key={e.evidence_id}>
              <summary>{e.source_kind === 'program_result' ? '程序计算' : '原文片段'} · {e.filename}</summary>
              <pre className="span-snippet">{e.text}</pre>
            </details>)}
          </div> : f.verified_quote && (
            <div className="finding-section">
              <div className="section-label">原文引用</div>
              <div className="span-snippet-box">
                <code className="span-snippet">{f.verified_quote}</code>
              </div>
              {f.material_filename && (
                <div className="muted">来源:{f.material_filename}</div>
              )}
            </div>
          )}
          {f.suggestion && (
            <div className="finding-section">
              <div className="section-label">
                待验证的建议
                <span
                  className={`suggestion-type-badge st-${f.suggestion_type}`}
                  title={
                    f.suggestion_type === 'fix'
                      ? '实验做法或代码有缺陷,需要修改'
                      : f.suggestion_type === 'narrow'
                        ? '主张范围过大,需要收窄'
                        : '信息不明确,需要补充澄清'
                  }
                >
                  {f.suggestion_type === 'fix'
                    ? '修复实验'
                    : f.suggestion_type === 'narrow'
                      ? '收窄主张'
                      : '补充澄清'}
                </span>
              </div>
              <div className="finding-suggestion">
                <p className="muted">{f.validation_status === 'manual_verification_required'
                  ? '此建议暂无对应的程序验证项，须人工复核依据和修改后果。'
                  : '尚未执行验证。修改后请上传实际记录，再到第五步核对原问题。'}</p>
                {!!f.validation_check_ids?.length && <p className="muted">修改后重查：{(result?.checks ?? [])
                  .filter(c => f.validation_check_ids?.includes(c.check_id)).map(c => c.title).join('、')}</p>}
                {f.suggestion_action ? (
                  <>
                    <div className="suggestion-line">
                      <span className="suggestion-part">具体怎么改</span>
                      {f.suggestion_action}
                    </div>
                    {f.suggestion_reason && (
                      <div className="suggestion-line">
                        <span className="suggestion-part">为什么</span>
                        {f.suggestion_reason}
                      </div>
                    )}
                    {f.suggestion_verify && (
                      <div className="suggestion-line">
                        <span className="suggestion-part">如何验证</span>
                        {f.suggestion_verify}
                      </div>
                    )}
                  </>
                ) : (
                  f.suggestion
                )}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
