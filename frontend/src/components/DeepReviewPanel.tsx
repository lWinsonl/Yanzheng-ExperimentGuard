import { useState } from 'react'
import type { DeepFinding } from '../types'
import { LEVEL_COLORS, LEVEL_LABELS } from '../types'
import { deepReview } from '../api'
import { LoadingDots } from './LoadingDots'

interface Props {
  sessionId: string
  /** 复核结果变化时通知父组件(用于导出报告等) */
  onFindingsChange?: (findings: DeepFinding[]) => void
}

/**
 * 模型复核面板:对规则发现的问题给出详细修复方案,并发现规则无法覆盖的复杂上下文。
 * 仅在接入模型时可用;所有引用已逐字校验,未通过校验的发现不会展示。
 */
export function DeepReviewPanel({ sessionId, onFindingsChange }: Props) {
  const [findings, setFindings] = useState<DeepFinding[]>([])
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [llmAvailable, setLlmAvailable] = useState(true)

  async function run() {
    setBusy(true)
    try {
      const res = await deepReview(sessionId)
      const list = res.deep_findings ?? []
      setFindings(list)
      setLoaded(true)
      setLlmAvailable(res.llm_available ?? true)
      onFindingsChange?.(list)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="deep-review-panel">
      <div className="agent-section-header">
        <span>模型复核(详细修改建议)</span>
        <button disabled={busy} onClick={run}>
          {busy ? '复核中…' : loaded ? '重新复核' : '运行模型复核'}
        </button>
      </div>
      {busy && <LoadingDots text="模型正在复核复杂上下文" />}
      {loaded && !busy && findings.length === 0 && (
        <div className="muted">
          {llmAvailable
            ? '模型未发现需要补充的问题。'
            : '未接入模型,此功能需要配置 LLM 密钥。'}
        </div>
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