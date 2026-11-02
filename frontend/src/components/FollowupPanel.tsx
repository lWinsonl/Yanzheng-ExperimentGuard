import { useCallback, useEffect, useState } from 'react'
import type { FollowupQuestion, FollowupStats } from '../types'
import {
  COST_LABELS,
  EVIDENCE_TYPE_LABELS,
} from '../types'
import {
  answerFollowup,
  generateRankedFollowups,
  getFollowupStats,
  listFollowups,
  skipFollowup,
} from '../api'

interface Props {
  sessionId: string
  onAnswerRecorded?: () => void
}

/** 主动追问面板:基于预期信息价值排序,展示"为何先问这个",回答后追踪发现变化。
 * 核心差异化(P1):从固定缺口清单升级为"回答哪个问题最可能改变审查结论",同时考虑补材料成本。
 */
export function FollowupPanel({ sessionId, onAnswerRecorded }: Props) {
  const [questions, setQuestions] = useState<FollowupQuestion[]>([])
  const [stats, setStats] = useState<FollowupStats | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})

  const loadFollowups = useCallback(async () => {
    try {
      const { questions: qs } = await listFollowups(sessionId)
      setQuestions(qs)
      try {
        const s = await getFollowupStats(sessionId)
        setStats(s)
      } catch {
        setStats(null)
      }
    } catch {
      setQuestions([])
    }
  }, [sessionId])

  useEffect(() => {
    loadFollowups()
  }, [loadFollowups])

  const handleGenerate = async () => {
    setBusy(true)
    setMessage('')
    try {
      const result = await generateRankedFollowups(sessionId)
      setQuestions(result.questions)
      setMessage(result.message)
      const s = await getFollowupStats(sessionId)
      setStats(s)
    } catch (e) {
      setMessage(`生成失败:${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setBusy(false)
    }
  }

  const handleAnswer = async (questionId: string) => {
    const text = answers[questionId]?.trim()
    if (!text) return
    setBusy(true)
    try {
      const updated = await answerFollowup(sessionId, questionId, text)
      setQuestions((prev) =>
        prev.map((q) => (q.question_id === questionId ? updated : q)),
      )
      setAnswers((prev) => ({ ...prev, [questionId]: '' }))
      const s = await getFollowupStats(sessionId)
      setStats(s)
      onAnswerRecorded?.()
    } catch (e) {
      setMessage(`回答失败:${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setBusy(false)
    }
  }

  const handleSkip = async (questionId: string) => {
    setBusy(true)
    try {
      const updated = await skipFollowup(sessionId, questionId)
      setQuestions((prev) =>
        prev.map((q) => (q.question_id === questionId ? updated : q)),
      )
      const s = await getFollowupStats(sessionId)
      setStats(s)
    } catch (e) {
      setMessage(`跳过失败:${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setBusy(false)
    }
  }

  const pending = questions.filter((q) => q.status === 'pending')
  const answered = questions.filter((q) => q.status === 'answered')
  const skipped = questions.filter((q) => q.status === 'skipped')

  return (
    <div className="followup-panel">
      <div className="panel-header">
        <h3>主动追问(按预期信息价值排序)</h3>
        <button
          className="btn-primary"
          onClick={handleGenerate}
          disabled={busy}
        >
          {busy ? '处理中...' : '生成追问'}
        </button>
      </div>
      <p className="panel-desc">
        系统评估每个问题「回答后最可能改变审查结论」的预期信息价值(EIV = 严重度 ×
        不确定性 × 可改变概率 ÷ 回答成本),优先追问价值最高的问题。
      </p>

      {message && <div className="followup-message">{message}</div>}

      {stats && questions.length > 0 && (
        <div className="followup-stats-bar">
          <span>共 {stats.total_questions} 问</span>
          <span>已回答 {stats.answered}</span>
          <span>完成率 {(stats.completion_rate * 100).toFixed(0)}%</span>
          <span>结论变化率 {(stats.change_rate * 100).toFixed(0)}%</span>
          <span>改变了 {stats.changed_findings} 条发现</span>
        </div>
      )}

      {questions.length === 0 && !busy && (
        <div className="followup-empty">
          尚无追问。审查报告生成后,点击「生成追问」获取按价值排序的问题。
        </div>
      )}

      {/* 待回答(按 EIV 排序) */}
      {pending.length > 0 && (
        <div className="followup-section">
          <h4>待回答({pending.length})</h4>
          {pending.map((q) => (
            <FollowupCard
              key={q.question_id}
              question={q}
              answerText={answers[q.question_id] || ''}
              busy={busy}
              onAnswerChange={(text) =>
                setAnswers((prev) => ({ ...prev, [q.question_id]: text }))
              }
              onAnswer={() => handleAnswer(q.question_id)}
              onSkip={() => handleSkip(q.question_id)}
            />
          ))}
        </div>
      )}

      {/* 已回答 */}
      {answered.length > 0 && (
        <div className="followup-section">
          <h4>已回答({answered.length})</h4>
          {answered.map((q) => (
            <FollowupAnsweredCard key={q.question_id} question={q} />
          ))}
        </div>
      )}

      {/* 已跳过 */}
      {skipped.length > 0 && (
        <div className="followup-section followup-skipped-section">
          <h4>已跳过({skipped.length})</h4>
          {skipped.map((q) => (
            <div key={q.question_id} className="followup-card skipped">
              <span className="followup-rank">#{q.rank}</span>
              <span className="followup-question-text">{q.question}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** 单条追问卡片:展示问题、EIV 评分解释、证据类型绑定、回答输入。 */
function FollowupCard({
  question: q,
  answerText,
  busy,
  onAnswerChange,
  onAnswer,
  onSkip,
}: {
  question: FollowupQuestion
  answerText: string
  busy: boolean
  onAnswerChange: (text: string) => void
  onAnswer: () => void
  onSkip: () => void
}) {
  const costKey =
    q.cost_factor <= 1 ? 'low' : q.cost_factor >= 3 ? 'high' : 'medium'

  return (
    <div className="followup-card">
      <div className="followup-card-header">
        <span className="followup-rank">#{q.rank}</span>
        <span className="followup-eiv">EIV {q.eiv_score.toFixed(2)}</span>
        <span className={`followup-cost cost-${costKey}`}>
          {COST_LABELS[costKey as keyof typeof COST_LABELS]}
        </span>
      </div>
      <div className="followup-question-text">{q.question}</div>

      {/* 为何先问这个:可解释评分 */}
      <div className="followup-explanation">{q.score_explanation}</div>

      {/* 证据类型与格式绑定 */}
      <div className="followup-meta">
        <span className="meta-tag evidence-type">
          期望证据:{EVIDENCE_TYPE_LABELS[q.evidence_type]}
        </span>
        {q.evidence_format && (
          <span className="meta-tag">格式:{q.evidence_format}</span>
        )}
        {q.target_finding_title && (
          <span className="meta-tag">关联发现:{q.target_finding_title}</span>
        )}
      </div>

      {q.what_to_provide && (
        <div className="followup-detail">
          <strong>请提供:</strong>
          {q.what_to_provide}
        </div>
      )}
      {q.why_needed && (
        <div className="followup-detail">
          <strong>为什么需要:</strong>
          {q.why_needed}
        </div>
      )}

      {/* 回答输入 */}
      <div className="followup-answer-area">
        <textarea
          value={answerText}
          onChange={(e) => onAnswerChange(e.target.value)}
          placeholder="在此输入你的回答或补充说明..."
          rows={3}
          disabled={busy}
        />
        <div className="followup-actions">
          <button
            className="btn-primary"
            onClick={onAnswer}
            disabled={busy || !answerText.trim()}
          >
            提交回答
          </button>
          <button className="btn-secondary" onClick={onSkip} disabled={busy}>
            跳过
          </button>
        </div>
      </div>
    </div>
  )
}

/** 已回答追问卡片:展示回答内容与发现变化追踪。 */
function FollowupAnsweredCard({ question: q }: { question: FollowupQuestion }) {
  return (
    <div className="followup-card answered">
      <div className="followup-card-header">
        <span className="followup-rank">#{q.rank}</span>
        <span className="followup-eiv">EIV {q.eiv_score.toFixed(2)}</span>
        <span
          className={`change-badge ${q.answer_changed_finding ? 'changed' : 'unchanged'}`}
        >
          {q.answer_changed_finding ? '改变了发现' : '未改变发现'}
        </span>
      </div>
      <div className="followup-question-text">{q.question}</div>
      <div className="followup-answer-text">
        <strong>你的回答:</strong>
        {q.answer_text}
      </div>
      <div
        className={`followup-change-detail ${q.answer_changed_finding ? 'changed' : 'unchanged'}`}
      >
        {q.finding_change_detail}
      </div>
    </div>
  )
}