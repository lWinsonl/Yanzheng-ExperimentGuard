import { useCallback, useEffect, useState } from 'react'
import type { ExtractedFact, FollowupQuestion } from '../types'
import { EVIDENCE_TYPE_LABELS } from '../types'
import {
  answerFollowup, confirmFact, generateRankedFollowups,
  listFacts, listFollowups, reviewFollowupAnswer, skipFollowup,
} from '../api'
import { FactCard } from './FactCard'

interface Props { sessionId: string; onAnswerRecorded?: () => void }

export function FollowupPanel({ sessionId, onAnswerRecorded }: Props) {
  const [questions, setQuestions] = useState<FollowupQuestion[]>([])
  const [facts, setFacts] = useState<ExtractedFact[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const load = useCallback(async () => {
    const [qs, fs] = await Promise.all([listFollowups(sessionId), listFacts(sessionId)])
    setQuestions(qs.questions); setFacts(fs)
  }, [sessionId])
  useEffect(() => { load().catch((e) => setMessage(String(e))) }, [load])
  async function act(action: () => Promise<unknown>) {
    setBusy(true); setMessage('')
    try { await action(); await load() }
    catch (e) { setMessage(e instanceof Error ? e.message : '操作未完成，请重试') }
    finally { setBusy(false) }
  }
  async function confirm(id: string, action: 'confirm' | 'correct' | 'reject', value?: string) {
    await act(async () => { await confirmFact(sessionId, id, action, value) })
  }
  return <div className="followup-panel">
    <div className="panel-header"><h3>补充最关键的证据</h3>
      <button className="btn-primary" disabled={busy}
        onClick={() => act(async () => {
          const res = await generateRankedFollowups(sessionId); setMessage(res.message)
        })}>{busy ? '处理中…' : questions.length ? '更新待回答追问' : '生成追问'}</button>
    </div>
    <p className="panel-desc">问题按影响、信息缺口和补充成本估计排序。先回答，再核对提取的事实，最后重新审查。补充说明会标明来源，不能代替实际运行记录。</p>
    {message && <div className="followup-message" role="status">{message}</div>}
    {!questions.length && <p className="muted">点击“生成追问”，查看当前优先需要补充什么。</p>}
    {questions.map((q) => {
      const answerFacts = facts.filter((f) => (q.answer_fact_ids ?? []).includes(f.fact_id))
      const hasPending = answerFacts.some((f) => f.status === 'pending_user_confirm')
      return <article className={`followup-card ${q.status}`} key={q.question_id}>
        <div className="followup-card-header"><span className="followup-rank">优先级 {q.rank}</span>
          <span className="meta-tag">需要：{EVIDENCE_TYPE_LABELS[q.evidence_type]}</span></div>
        <h4>{q.question}</h4>
        {q.what_to_provide && <p>请提供：{q.what_to_provide}</p>}
        {q.why_needed && <p className="muted">用途：{q.why_needed}</p>}
        <details><summary>为什么先问这个</summary><p>{q.score_explanation}</p>
          <p className="muted">排序因子为估计值，尚未经实际完成率数据校准。</p></details>
        {q.status === 'pending' && <div className="followup-answer-area">
          <label htmlFor={`answer-${q.question_id}`}>补充回答或代码、结果片段</label>
          <textarea id={`answer-${q.question_id}`} rows={3} maxLength={20000}
            value={answers[q.question_id] ?? ''} disabled={busy}
            onChange={(e) => setAnswers({ ...answers, [q.question_id]: e.target.value })}
            placeholder="说明实际做了什么；有代码或运行记录时请一并粘贴。" />
          <div className="followup-actions">
            <button className="btn-primary" disabled={busy || !answers[q.question_id]?.trim()}
              onClick={() => act(async () => {
                await answerFollowup(sessionId, q.question_id, answers[q.question_id].trim())
                setAnswers((prev) => ({ ...prev, [q.question_id]: '' }))
                setMessage('回答已保存，请核对下面的新事实。')
              })}>保存回答并提取事实</button>
            <button disabled={busy} onClick={() => act(() => skipFollowup(sessionId, q.question_id))}>暂时跳过</button>
          </div>
        </div>}
        {q.status === 'answered' && <>
          <p className="followup-answer-text"><strong>你的回答：</strong>{q.answer_text}</p>
          {q.review_state === 'awaiting_confirmation' && <>
            <p>逐条核对以下内容。确认表示提取无误，不代表运行结果已被独立验证。</p>
            {answerFacts.map((fact) => <FactCard key={fact.fact_id} sessionId={sessionId} fact={fact} onConfirm={confirm} />)}
            <button className="btn-primary" disabled={busy || hasPending || !answerFacts.length}
              onClick={() => act(async () => {
                await reviewFollowupAnswer(sessionId, q.question_id); onAnswerRecorded?.()
                setMessage('审查已更新，请查看变化说明。')
              })}>{hasPending ? '请先核对全部新事实' : '重新审查并查看变化'}</button>
          </>}
          <p className="followup-change-detail" role="status">{q.finding_change_detail}</p>
        </>}
        {q.status === 'skipped' && <p className="muted">已暂时跳过；仍可通过补充材料处理相关发现。</p>}
      </article>
    })}
  </div>
}
