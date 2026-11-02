import { useCallback, useState } from 'react'
import { VersionDiffPanel } from '../components/VersionDiffPanel'
import { MigrationQuiz } from '../components/MigrationQuiz'

interface Props { sessionId: string; onBack: () => void; onAddMaterial: () => void }

export function RecheckPage({ sessionId, onBack, onAddMaterial }: Props) {
  const [reviewed, setReviewed] = useState(false)
  const markReviewed = useCallback(() => setReviewed(true), [])
  return <div className="page">
    <h2>第五步：修改、复查与迁移练习</h2>
    <p className="muted">先上传修改后的材料并确认新事实，再填写修改理由。复查保留修改前的基准报告，普通的重新审查不会覆盖它。</p>
    <div className="page-actions">
      <button onClick={onBack}>返回审查报告</button>
      <button className="primary" onClick={onAddMaterial}>补充修改后的材料</button>
    </div>
    <section className="workflow-step">
      <VersionDiffPanel sessionId={sessionId} onResultChange={markReviewed} />
    </section>
    {reviewed ? <section className="workflow-step">
      <h3>换一个情境，再试一次</h3>
      <p className="muted">用新问题检查你的推理。单次练习反馈用于改进，不作为已掌握方法的证明。</p>
      <MigrationQuiz sessionId={sessionId} />
    </section> : <p className="muted">完成一次复查后，这里会出现针对原问题的迁移练习。</p>}
  </div>
}
