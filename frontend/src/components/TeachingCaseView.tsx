import { useState } from 'react'
import type { TeachingCase } from '../types'
import { generateTeachingCase } from '../api'

interface Props {
  sessionId: string
}

/**
 * 教学小案例:复查后给一个新案例,让学生自己判断实验漏洞,
 * 训练实验设计能力,而不只是替学生找错。
 * 参考思路默认隐藏,学生先思考再展开。
 */
export function TeachingCaseView({ sessionId }: Props) {
  const [caseData, setCaseData] = useState<TeachingCase | null>(null)
  const [showHint, setShowHint] = useState(false)
  const [showAnswer, setShowAnswer] = useState(false)
  const [busy, setBusy] = useState(false)

  async function load() {
    setBusy(true)
    setShowHint(false)
    setShowAnswer(false)
    try {
      setCaseData(await generateTeachingCase(sessionId))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="teaching-case">
      <div className="agent-section-header">
        <span>教学小案例:自己找漏洞</span>
        <button disabled={busy} onClick={load}>
          {busy ? '生成中…' : caseData ? '换一个案例' : '生成案例'}
        </button>
      </div>

      {caseData && (
        <div className="case-content">
          <h4>{caseData.case_title}</h4>
          <div className="case-desc">{caseData.case_description}</div>
          <div className="case-question">
            <strong>思考:</strong>
            {caseData.question}
          </div>

          {!showHint && (
            <button className="case-btn" onClick={() => setShowHint(true)}>
              想不出来?看提示
            </button>
          )}
          {showHint && (
            <div className="case-hint">
              <strong>提示:</strong>
              {caseData.hint}
            </div>
          )}

          {!showAnswer && (
            <button className="case-btn primary" onClick={() => setShowAnswer(true)}>
              我有思路了,看参考答案
            </button>
          )}
          {showAnswer && (
            <div className="case-answer">
              <strong>参考思路:</strong>
              {caseData.reference_answer}
            </div>
          )}

          <div className="muted case-meta">
            来源:{caseData.source === 'llm' ? '模型生成' : '预设案例库'}
            {caseData.related_rule && ` · 关联规则:${caseData.related_rule}`}
          </div>
        </div>
      )}
    </div>
  )
}