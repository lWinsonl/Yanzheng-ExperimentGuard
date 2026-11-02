import { useCallback, useEffect, useState } from 'react'
import type { MigrationAnswer, MigrationQuestion } from '../types'
import {
  answerMigration,
  generateMigrationQuestion,
  listMigrationQuestions,
} from '../api'

interface Props {
  sessionId: string
}

const DIMENSION_LABELS: Record<string, string> = {
  identifies_core_issue: '识别核心问题',
  explains_why: '解释原因',
  proposes_fix: '提出修改',
  reasoning_quality: '推理质量',
}

/** 迁移题测验组件:不同表面情境、同一方法要点,评分看推理过程而非只看答案。
 * 核心差异化(P2):验证学生是否真正学会了方法,而不是只记住了这次实验的答案。
 */
export function MigrationQuiz({ sessionId }: Props) {
  const [questions, setQuestions] = useState<MigrationQuestion[]>([])
  const [activeQuestion, setActiveQuestion] = useState<MigrationQuestion | null>(
    null,
  )
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<MigrationAnswer | null>(null)
  const [busy, setBusy] = useState(false)
  const [showReference, setShowReference] = useState(false)
  const [message, setMessage] = useState('')

  const loadQuestions = useCallback(async () => {
    try {
      const { questions: qs } = await listMigrationQuestions(sessionId)
      setQuestions(qs)
      if (qs.length > 0 && !activeQuestion) {
        setActiveQuestion(qs[qs.length - 1])
      }
    } catch {
      setQuestions([])
    }
  }, [sessionId, activeQuestion])

  useEffect(() => {
    loadQuestions()
  }, [loadQuestions])

  const handleGenerate = async () => {
    setBusy(true)
    setMessage('')
    setResult(null)
    setAnswer('')
    setShowReference(false)
    try {
      const response = await generateMigrationQuestion(sessionId)
      if (!response.question) {
        setMessage(response.message || '暂时无法生成迁移题,请先完成实验审查')
        return
      }
      const q = response.question
      setActiveQuestion(q)
      setQuestions((prev) => [...prev, q])
      setMessage('迁移题已生成')
    } catch (e) {
      setMessage(`生成失败:${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setBusy(false)
    }
  }

  const handleSubmit = async () => {
    if (!activeQuestion || !answer.trim()) return
    setBusy(true)
    setMessage('')
    try {
      const response = await answerMigration(sessionId, activeQuestion.question_id, answer)
      if (!response.answer) {
        setMessage(response.message || '评分未完成,请稍后重试')
        return
      }
      const r = response.answer
      setResult(r)
      setMessage(r.score_status === 'model_feedback'
        ? '已生成本次推理反馈。请核对理由，单次结果不代表已掌握方法。'
        : '作答已保存，本次未给分。请对照参考思路自查，或请教师复核。')
    } catch (e) {
      setMessage(`提交失败:${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setBusy(false)
    }
  }

  const handleSelectQuestion = (q: MigrationQuestion) => {
    setActiveQuestion(q)
    setResult(null)
    setAnswer('')
    setShowReference(false)
    setMessage('')
  }

  return (
    <div className="migration-panel">
      <div className="panel-header">
        <h3>学习迁移评估</h3>
        <button className="btn-primary" onClick={handleGenerate} disabled={busy}>
          {busy ? '生成中...' : '生成迁移题'}
        </button>
      </div>

      <p className="panel-desc">
        基于你实验中发现的问题,生成一个<strong>不同表面情境</strong>但
        <strong>同一方法要点</strong>的新实验场景。评分看的是你的推理过程
        (是否识别了核心问题、是否解释了为什么、是否提出了修改)。模型不可用时提供自查建议，不输出掌握分数。
      </p>

      {/* 已有迁移题列表 */}
      {questions.length > 1 && (
        <div className="migration-question-list">
          {questions.map((q) => (
            <button
              key={q.question_id}
              className={`question-tab ${
                activeQuestion?.question_id === q.question_id ? 'active' : ''
              }`}
              onClick={() => handleSelectQuestion(q)}
            >
              {q.scenario.slice(0, 30)}...
            </button>
          ))}
        </div>
      )}

      {message && <div className="migration-message">{message}</div>}

      {activeQuestion ? (
        <div className="migration-question-card">
          <div className="question-section">
            <strong>新情境:</strong>
            <p>{activeQuestion.scenario}</p>
          </div>
          <div className="question-section">
            <strong>方法要点:</strong>
            <p>{activeQuestion.method_point}</p>
          </div>
          <div className="question-section question-main">
            <strong>问题:</strong>
            <p>{activeQuestion.question}</p>
          </div>
          {activeQuestion.hint && (
            <div className="question-hint">提示:{activeQuestion.hint}</div>
          )}

          {/* 作答区 */}
          <div className="migration-answer-area">
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="请写出你的推理过程:这个新实验中存在什么问题?为什么?你会怎么修改?"
              rows={5}
              disabled={!!result}
            />
            {!result && (
              <button
                className="btn-primary"
                onClick={handleSubmit}
                disabled={busy || !answer.trim()}
              >
                {busy ? '评分中...' : '提交作答'}
              </button>
            )}
          </div>

          {/* 四维评分结果 */}
          {result && (
            <div className="migration-score-card">
              <div className="score-header">
                <span className="score-total">{result.score_status === 'model_feedback' && result.total_score != null
                  ? `本次模型参考分：${(result.total_score * 100).toFixed(0)} 分` : '本次未评分'}</span>
                <span className="score-source">{result.score_status === 'model_feedback' ? '模型反馈，待核对' : '自查建议'}</span>
              </div>
              {result.score_status === 'model_feedback' && <>
              <div className="score-dimensions">
                {(
                  ['identifies_core_issue', 'explains_why', 'proposes_fix', 'reasoning_quality'] as const
                ).map((dim) => (
                  <div key={dim} className="score-dimension">
                    <span className="dim-label">{DIMENSION_LABELS[dim]}</span>
                    <div className="dim-bar-bg">
                      <div
                        className="dim-bar"
                        style={{
                          width: `${(result[dim] ?? 0) * 100}%`,
                          background:
                            (result[dim] ?? 0) >= 0.6 ? '#1e8e3e' : '#e37400',
                        }}
                      />
                    </div>
                    <span className="dim-value">
                      {((result[dim] ?? 0) * 100).toFixed(0)}
                    </span>
                  </div>
                ))}
              </div>
              </>}
              {result.score_status !== 'model_feedback' && <button className="btn-secondary"
                onClick={() => { setResult(null); setMessage('可修改作答后重新提交，系统将再次尝试获取模型反馈。') }}>编辑或重试</button>}
              {result.feedback && (
                <div className="score-feedback">{result.feedback}</div>
              )}
            </div>
          )}

          {/* 参考答案(作答后可展开) */}
          {result && activeQuestion.reference_answer && (
            <div className="reference-answer-area">
              <button
                className="btn-secondary"
                onClick={() => setShowReference(!showReference)}
              >
                {showReference ? '隐藏参考答案' : '查看参考答案'}
              </button>
              {showReference && (
                <div className="reference-answer-text">
                  {activeQuestion.reference_answer}
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="migration-empty">
          {busy
            ? '正在生成迁移题...'
            : '尚无迁移题。点击上方"生成迁移题",系统将基于你实验中发现的最严重问题,生成一个不同情境、同一方法要点的迁移题。'}
        </div>
      )}
    </div>
  )
}
