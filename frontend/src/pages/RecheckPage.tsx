import { useState } from 'react'
import type { RecheckResult } from '../types'
import { runRecheck } from '../api'

interface Props {
  sessionId: string
  onBack: () => void
  onAddMaterial: () => void
}

/** 第五步:修改后复查。提交修改理由,系统比较前后版本。 */
export function RecheckPage({ sessionId, onBack, onAddMaterial }: Props) {
  const [note, setNote] = useState('')
  const [result, setResult] = useState<RecheckResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    setBusy(true)
    setError('')
    try {
      setResult(await runRecheck(sessionId, note))
    } catch (e) {
      setError(e instanceof Error ? e.message : '复查失败')
    } finally {
      setBusy(false)
    }
  }

  const resolved = result?.comparisons.filter((c) => c.resolved) ?? []
  const remaining = result?.comparisons.filter((c) => !c.resolved) ?? []

  return (
    <div className="page">
      <h2>第五步:修改后复查</h2>
      <p className="muted">
        根据报告修改实验或补充材料后,回到<a onClick={onAddMaterial}>第二步</a>
        上传新材料、确认新事实,然后在此提交修改理由。系统会对比前后版本,
        显示哪些疑点已不再触发、哪些仍待核实。
      </p>

      <div className="form-group">
        <label>修改理由</label>
        <textarea
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="例如:已将数据划分改为按设备划分(GroupShuffleSplit),并补充了设备编号交集检查结果。"
        />
      </div>

      <div className="page-actions">
        <button onClick={onBack}>上一步</button>
        <button onClick={onAddMaterial}>去补充材料/确认事实</button>
        <button className="primary" disabled={busy} onClick={submit}>
          {busy ? '复查中…' : '运行复查'}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <div className="recheck-result">
          <h3>复查结果</h3>
          {result.revision_note && (
            <div className="muted">修改理由:{result.revision_note}</div>
          )}

          {resolved.length > 0 && (
            <div className="recheck-section">
              <h4 className="success-text">已解除的疑点({resolved.length})</h4>
              {resolved.map((c) => (
                <div key={c.finding_id} className="recheck-item resolved">
                  <span className="check-icon">✓</span>
                  <div>
                    <div className="recheck-title">{c.title}</div>
                    <div className="muted">{c.note}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {remaining.length > 0 && (
            <div className="recheck-section">
              <h4 className="warn-text">仍待核实({remaining.length})</h4>
              {remaining.map((c) => (
                <div key={c.finding_id} className="recheck-item remaining">
                  <span className="check-icon">!</span>
                  <div>
                    <div className="recheck-title">{c.title}</div>
                    <div className="muted">{c.note}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {result.newly_raised.length > 0 && (
            <div className="recheck-section">
              <h4 className="warn-text">新发现的疑点({result.newly_raised.length})</h4>
              <div className="muted">
                新材料引入了新的审查维度,请查看最新报告详情。
              </div>
            </div>
          )}

          {resolved.length === 0 && remaining.length === 0 && (
            <div className="success">
              本次复查未发现疑点。你的主张、计划与执行在已审查维度上一致。
            </div>
          )}
        </div>
      )}

    </div>
  )
}