import { useCallback, useEffect, useState } from 'react'
import type { ExtractedFact } from '../types'
import { confirmAllPending, confirmFact, listFacts } from '../api'
import { FactCard } from '../components/FactCard'

interface Props {
  sessionId: string
  onNext: () => void
  onBack: () => void
}

/** 第三步:确认提取的事实。系统不把猜测当事实——学生先核对再放行。 */
export function FactConfirmPage({ sessionId, onNext, onBack }: Props) {
  const [facts, setFacts] = useState<ExtractedFact[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      setFacts(await listFacts(sessionId))
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    }
  }, [sessionId])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function handleConfirm(
    factId: string,
    action: 'confirm' | 'correct' | 'reject',
    correctedValue?: string,
  ) {
    try {
      await confirmFact(sessionId, factId, action, correctedValue)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败')
    }
  }

  async function handleConfirmAll() {
    setBusy(true)
    try {
      await confirmAllPending(sessionId)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败')
    } finally {
      setBusy(false)
    }
  }

  const pending = facts.filter((f) => f.status === 'pending_user_confirm')
  const confirmed = facts.filter(
    (f) => f.status === 'confirmed' || f.status === 'corrected',
  )
  const rejected = facts.filter((f) => f.status === 'rejected')

  return (
    <div className="page">
      <h2>第三步:确认提取的事实</h2>
      <p className="muted">
        系统从材料中提取了以下可核对的事实,每条都附有原文片段。
        请逐条核对后<strong>确认 / 纠正 / 拒绝</strong>——
        只有你确认的事实才会进入审查,系统不把猜测当事实。
      </p>

      <div className="fact-stats">
        <span>待确认:{pending.length}</span>
        <span>已确认/纠正:{confirmed.length}</span>
        <span>已拒绝:{rejected.length}</span>
      </div>

      {error && <div className="error">{error}</div>}

      {pending.length > 0 && (
        <>
          <div className="page-actions">
            <button className="primary" disabled={busy} onClick={handleConfirmAll}>
              全部确认(已逐条过目后可批量)
            </button>
          </div>
          <div className="fact-grid">
            {pending.map((f) => (
              <FactCard
                key={f.fact_id}
                sessionId={sessionId}
                fact={f}
                onConfirm={handleConfirm}
              />
            ))}
          </div>
        </>
      )}

      {confirmed.length > 0 && (
        <>
          <h4>已确认的事实</h4>
          <div className="fact-grid">
            {confirmed.map((f) => (
              <FactCard
                key={f.fact_id}
                sessionId={sessionId}
                fact={f}
                onConfirm={handleConfirm}
              />
            ))}
          </div>
        </>
      )}

      {rejected.length > 0 && (
        <>
          <h4>已拒绝的事实</h4>
          <div className="fact-grid collapsed">
            {rejected.map((f) => (
              <FactCard
                key={f.fact_id}
                sessionId={sessionId}
                fact={f}
                onConfirm={handleConfirm}
              />
            ))}
          </div>
        </>
      )}

      {facts.length === 0 && (
        <div className="empty">尚未提取到任何事实,请返回上一步补充材料。</div>
      )}

      <div className="page-actions">
        <button onClick={onBack}>上一步</button>
        <button
          className="primary"
          onClick={onNext}
          disabled={pending.length > 0}
          title={pending.length > 0 ? '请先确认所有待确认事实' : undefined}
        >
          下一步:运行审查
        </button>
      </div>
    </div>
  )
}