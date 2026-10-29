import { useState } from 'react'
import type { ExtractedFact } from '../types'
import { CATEGORY_LABELS, STATUS_LABELS } from '../types'
import { SourceSpanView } from './SourceSpanView'

interface Props {
  sessionId: string
  fact: ExtractedFact
  onConfirm: (
    factId: string,
    action: 'confirm' | 'correct' | 'reject',
    correctedValue?: string,
  ) => Promise<void>
}

/**
 * 事实卡片:证据链中间层的可视化与用户裁决。
 * 学生核对原文片段后,确认 / 纠正 / 拒绝该事实。
 * 只有确认/纠正的事实才进入审查。
 */
export function FactCard({ sessionId, fact, onConfirm }: Props) {
  const [correcting, setCorrecting] = useState(false)
  const [correctedValue, setCorrectedValue] = useState(fact.corrected_value ?? fact.value)
  const [busy, setBusy] = useState(false)

  const pending = fact.status === 'pending_user_confirm'
  const statusColor =
    fact.status === 'confirmed'
      ? '#188038'
      : fact.status === 'corrected'
        ? '#1a73e8'
        : fact.status === 'rejected'
          ? '#5f6368'
          : '#e37400'

  async function act(action: 'confirm' | 'correct' | 'reject', value?: string) {
    setBusy(true)
    try {
      await onConfirm(fact.fact_id, action, value)
      setCorrecting(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`fact-card status-${fact.status}`}>
      <div className="fact-header">
        <span className="fact-category">{CATEGORY_LABELS[fact.category]}</span>
        <span className="fact-status" style={{ color: statusColor }}>
          {STATUS_LABELS[fact.status]}
        </span>
      </div>
      <div className="fact-value">
        {fact.status === 'corrected' && fact.corrected_value ? (
          <>
            <span className="fact-old">{fact.value}</span>
            <span className="fact-arrow"> → </span>
            <strong>{fact.corrected_value}</strong>
          </>
        ) : (
          <strong>{fact.value}</strong>
        )}
      </div>
      {fact.note && <div className="fact-note muted">{fact.note}</div>}
      <SourceSpanView sessionId={sessionId} span={fact.source} />
      {pending && (
        <div className="fact-actions">
          <button disabled={busy} onClick={() => act('confirm')}>
            确认无误
          </button>
          <button disabled={busy} onClick={() => setCorrecting(!correcting)}>
            纠正
          </button>
          <button disabled={busy} onClick={() => act('reject')}>
            拒绝(提取错误)
          </button>
        </div>
      )}
      {correcting && (
        <div className="fact-correct">
          <input
            value={correctedValue}
            onChange={(e) => setCorrectedValue(e.target.value)}
            placeholder="输入纠正后的事实值"
          />
          <button disabled={busy} onClick={() => act('correct', correctedValue)}>
            提交纠正
          </button>
          <button disabled={busy} onClick={() => setCorrecting(false)}>
            取消
          </button>
        </div>
      )}
    </div>
  )
}