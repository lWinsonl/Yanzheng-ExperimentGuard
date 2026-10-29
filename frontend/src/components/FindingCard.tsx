import type { Finding } from '../types'
import { CATEGORY_LABELS, LEVEL_COLORS, LEVEL_LABELS } from '../types'
import { SourceSpanView } from './SourceSpanView'

interface Props {
  sessionId: string
  finding: Finding
  claimTexts: Record<string, string>
}

/**
 * 审查发现卡片:证据链顶层的可视化。
 * 强制回答四件事:依据在哪、影响哪句结论、还缺什么、下一步做什么。
 */
export function FindingCard({ sessionId, finding, claimTexts }: Props) {
  const color = LEVEL_COLORS[finding.level]
  const suggestionLabel =
    finding.suggestion_type === 'narrow'
      ? '建议(收窄结论)'
      : finding.suggestion_type === 'clarify'
        ? '建议(补充说明)'
        : '建议(修改实验)'

  return (
    <div className="finding-card" style={{ borderLeftColor: color }}>
      <div className="finding-header">
        <span className="finding-level" style={{ background: color }}>
          {LEVEL_LABELS[finding.level]}
        </span>
        <span className="finding-title">{finding.title}</span>
      </div>

      {/* 影响哪句结论 */}
      {finding.claim_ids.length > 0 && (
        <div className="finding-section">
          <div className="section-label">影响的主张</div>
          {finding.claim_ids.map((cid) => (
            <div key={cid} className="finding-claim">
              {claimTexts[cid] ?? cid}
            </div>
          ))}
        </div>
      )}

      {/* 依据在哪 */}
      {finding.evidence.length > 0 && (
        <div className="finding-section">
          <div className="section-label">依据(可回溯原文)</div>
          {finding.evidence.map((ref) => (
            <div key={ref.fact_id} className="finding-evidence">
              <span className="evidence-cat">{CATEGORY_LABELS[ref.category]}:</span>
              <strong>{ref.value}</strong>
              <SourceSpanView sessionId={sessionId} span={ref.source} />
            </div>
          ))}
        </div>
      )}

      {/* 还缺什么 */}
      {finding.missing_evidence.length > 0 && (
        <div className="finding-section">
          <div className="section-label">还缺什么证据</div>
          <ul className="finding-missing">
            {finding.missing_evidence.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 下一步做什么 */}
      {finding.suggestion && (
        <div className="finding-section">
          <div className="section-label">{suggestionLabel}</div>
          <div className="finding-suggestion">{finding.suggestion}</div>
        </div>
      )}

      {/* 推理过程 */}
      {finding.reasoning && (
        <div className="finding-section">
          <div className="section-label">为什么触发</div>
          <div className="finding-reasoning muted">{finding.reasoning}</div>
        </div>
      )}
    </div>
  )
}