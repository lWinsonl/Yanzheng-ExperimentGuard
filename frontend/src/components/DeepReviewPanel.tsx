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
  ok_no_findings: { text: '模型已完成复核,未发现需要补充的问题。', cls: 'success' },
  llm_unavailable: {
    text: '未接入模型,此功能需要配置 LLM 密钥(当前运行在启发式模式)。',
    cls: 'warn',
  },
  llm_call_failed: {
    text: '模型调用失败(超时或网络异常),本次复核未完成,请稍后重试。',
    cls: 'error',
  },
  llm_parse_failed: {
    text: '模型返回了内容但无法解析为结构化结果,本次复核未完成,请重试。',
    cls: 'error',
  },
}

/** 覆盖范围面板:告知用户模型实际检查了哪些材料、哪些内容因过长被截断 */
function CoveragePanel({ coverage }: { coverage: MaterialCoverage[] }) {
  if (coverage.length === 0) return null
  const hasTruncated = coverage.some((c) => c.truncated)
  return (
    <div className={`coverage-panel${hasTruncated ? ' has-truncated' : ''}`}>
      <div className="coverage-title">
        复核范围{hasTruncated ? '(部分材料因过长被截断,未检查部分不会计入结论)' : ''}
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
              检查了前 {c.checked_chars} / {c.total_chars} 字符,其余未检查
            </span>
          ) : (
            <span className="coverage-note ok">已全量检查({c.total_chars} 字符)</span>
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
        <span>模型复核(详细修改建议)</span>
        <button disabled={busy} onClick={run}>
          {busy ? '复核中…' : result ? '重新复核' : '运行模型复核'}
        </button>
      </div>
      {busy && <LoadingDots text="模型正在复核复杂上下文" />}
      {error && !busy && (
        <div className="error">复核请求失败:{error}</div>
      )}
      {result && !busy && statusInfo && statusInfo.text && (
        <div className={statusInfo.cls}>{statusInfo.text}</div>
      )}
      {result && !busy && result.coverage.length > 0 && (
        <CoveragePanel coverage={result.coverage} />
      )}
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
            {f.quote_verified && (
              <span className="verify-badge" title="引用已逐字校验">
                ✓ 引用已校验
              </span>
            )}
          </div>
          {f.reasoning && (
            <div className="finding-section">
              <div className="section-label">推理</div>
              <div className="finding-reasoning">{f.reasoning}</div>
            </div>
          )}
          {f.verified_quote && (
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
                修改建议
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