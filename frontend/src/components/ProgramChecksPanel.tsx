import type { ProgramCheck, RepairCheck } from '../types'

const CHECK_LABELS = { passed: '当前记录通过', failed: '当前记录未通过', unknown: '尚无法核实' }
const REPAIR_LABELS = {
  still_fails: '问题仍在', passed_on_records: '新记录通过本项验证',
  scope_unconfirmed: '当前通过，实验范围待确认', not_verified: '尚未验证',
}

export function ProgramChecksPanel({ checks }: { checks: ProgramCheck[] }) {
  if (!checks.length) return null
  return <section className="workflow-step" aria-label="程序核对结果">
    <h3>程序核对结果</h3>
    <p className="muted">完整读取已确认记录后计算。通过一项检查，不代表整个实验正确。</p>
    {checks.map(c => <div className="finding-card" key={c.check_id}>
      <div className="finding-header"><strong>{c.title}</strong><span className={c.status === 'failed' ? 'error' : 'muted'}>{CHECK_LABELS[c.status]}</span></div>
      <p>{c.basis}</p>
      <p className="muted">{c.boundary}</p>
    </div>)}
  </section>
}

export function RepairChecksPanel({ checks }: { checks: RepairCheck[] }) {
  if (!checks.length) return null
  return <section className="workflow-step" aria-label="修改后的实际验证">
    <h3>修改后，原问题是否还在？</h3>
    <p className="muted">只用新的已确认记录重查原问题。建议写得具体，不等于已经修复。</p>
    {checks.map((c, i) => <div className="finding-card" key={i}>
      <strong>{c.title} · {REPAIR_LABELS[c.status]}</strong>
      <p>{c.detail}</p>
      {typeof c.before_values.overlap_count === 'number' && <p>原编号交集：{c.before_values.overlap_count}；当前：{typeof c.after_values.overlap_count === 'number' ? c.after_values.overlap_count : '缺少可核对记录'}</p>}
      <p className="muted">未独立核实原始数据、范围声明与实际训练过程。</p>
    </div>)}
  </section>
}
