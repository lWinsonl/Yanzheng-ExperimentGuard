import { useState } from 'react'
import type { DeepFinding } from '../types'
import { LEVEL_COLORS, LEVEL_LABELS } from '../types'
import { deepReview } from '../api'
import { LoadingDots } from './LoadingDots'

interface Props {
  sessionId: string
}

/**
 * 模型复核面板:处理规则无法覆盖的复杂上下文。
 * 仅在接入模型时可用;所有引用已逐字校验,未通过校验的发现不会展示。
 */
export function DeepReviewPanel({ sessionId }: Props) {
  const [findings, setFindings] = useState<DeepFinding[]>([])
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)

  async function run() {
    setBusy(true)
    try {
      const res = await deepReview(sessionId)
      setFindings(res.deep_findings ?? [])
      setLoaded(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="deep-review-panel">
      <div className="agent-section-header">
        <span>模型复核(复杂上下文)</span>
        <button disabled={busy} onClick={run}>
          {busy ? '复核中…' : loaded ? '重新复核' : '运行模型复核'}
        </button>
      </div>
      {busy && <LoadingDots text="模型正在复核复杂上下文" />}
      {loaded && !busy && findings.length === 0 && (
        <div className="muted">
          模型未发现规则之外的问题(或未接入模型,此功能需要配置 LLM)。
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
              <div className="section-label">建议</div>
              <div className="finding-suggestion">{f.suggestion}</div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}