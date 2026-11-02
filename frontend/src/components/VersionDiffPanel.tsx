import { useEffect, useState } from 'react'
import type {
  VersionDiffComparison,
  VersionDiffResult,
  VersionDiffStats,
  VersionDiffStatus,
} from '../types'
import {
  ALIGNMENT_COLORS,
  ALIGNMENT_LABELS,
  VDIFF_STATUS_COLORS,
  VDIFF_STATUS_LABELS,
} from '../types'
import {
  addManualLabel,
  getLatestVersionDiff,
  getVersionDiffStats,
  runVersionDiff,
} from '../api'

interface Props {
  sessionId: string
  onResultChange?: () => void
}

/** 版本差异复审面板:稳定身份配对、五态判定、修改理由对照、人工标签。
 * 核心差异化(P2):同时解决"问题是否真的被修复"和"学生能否把方法迁移到新实验"。
 */
export function VersionDiffPanel({ sessionId, onResultChange }: Props) {
  const [diff, setDiff] = useState<VersionDiffResult | null>(null)
  const [stats, setStats] = useState<VersionDiffStats | null>(null)
  const [revisionNote, setRevisionNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [labeledIds, setLabeledIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    let active = true
    getLatestVersionDiff(sessionId).then((d) => {
      if (!active) return
      setDiff(d)
      setRevisionNote((previous) => previous || d.revision_alignment.revision_note)
      onResultChange?.()
    }).catch(() => { if (active) setDiff(null) })
    getVersionDiffStats(sessionId).then((value) => { if (active) setStats(value) })
      .catch(() => { if (active) setStats(null) })
    return () => { active = false }
  }, [sessionId, onResultChange])

  const handleRun = async () => {
    setBusy(true)
    setMessage('')
    try {
      const d = await runVersionDiff(sessionId, revisionNote)
      setDiff(d)
      onResultChange?.()
      setMessage('版本差异复审完成')
      const s = await getVersionDiffStats(sessionId)
      setStats(s)
    } catch (e) {
      setMessage(`复审失败:${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setBusy(false)
    }
  }

  const handleLabel = async (
    comparisonId: string,
    actualStatus: VersionDiffStatus,
  ) => {
    try {
      await addManualLabel(sessionId, comparisonId, actualStatus, 'user')
      setLabeledIds((prev) => new Set(prev).add(comparisonId))
      const s = await getVersionDiffStats(sessionId)
      setStats(s)
    } catch (e) {
      setMessage(`标注失败:${e instanceof Error ? e.message : '未知错误'}`)
    }
  }

  if (!diff && !busy) {
    return (
      <div className="vdiff-panel">
        <div className="panel-header">
          <h3>版本差异复审</h3>
        </div>
        <p className="panel-desc">
          修改实验后,重新审查并对比前后报告。系统对比修改前后的发现，说明哪些问题仍在、哪些有变化，以及哪些还缺证据。
        </p>
        <div className="vdiff-run-area">
          <textarea
            value={revisionNote}
            onChange={(e) => setRevisionNote(e.target.value)}
            placeholder="请描述你做了什么修改(修改理由),如:已改为按设备划分,使用 GroupShuffleSplit..."
            rows={3}
          />
          <button
            className="btn-primary"
            onClick={handleRun}
            disabled={busy || !revisionNote.trim()}
          >
            {busy ? '复审中...' : '运行版本差异复审'}
          </button>
        </div>
        {message && <div className="vdiff-message">{message}</div>}
      </div>
    )
  }

  const grouped = (diff?.comparisons ?? []).reduce<
    Record<string, VersionDiffComparison[]>
  >((acc, c) => {
    ;(acc[c.status] ??= []).push(c)
    return acc
  }, {})

  const statusOrder: VersionDiffStatus[] = [
    'resolved',
    'mitigated',
    'persists',
    'new_issue',
    'insufficient_evidence',
  ]

  return (
    <div className="vdiff-panel">
      <div className="panel-header">
        <h3>版本差异复审</h3>
        <button className="btn-secondary" onClick={handleRun} disabled={busy || !revisionNote.trim()}>
          {busy ? '复审中...' : '重新复审'}
        </button>
      </div>

      <div className="vdiff-run-area">
        <label htmlFor="revision-note">本轮修改理由</label>
        <textarea id="revision-note" value={revisionNote} rows={3} disabled={busy}
          onChange={(e) => setRevisionNote(e.target.value)} placeholder="补充本轮实际修改的内容，再运行复查。" />
      </div>

      {/* 修改理由对照 */}
      {diff?.revision_alignment && (
        <div className="vdiff-alignment">
          <div className="alignment-header">
            <span>修改理由对照</span>
            <span
              className="alignment-badge"
              style={{
                color: ALIGNMENT_COLORS[diff.revision_alignment.alignment],
                borderColor: ALIGNMENT_COLORS[diff.revision_alignment.alignment],
              }}
            >
              {ALIGNMENT_LABELS[diff.revision_alignment.alignment]}
            </span>
          </div>
          <div className="alignment-detail">
            {diff.revision_alignment.alignment_detail}
          </div>
          {diff.revision_alignment.claimed_changes.length > 0 && (
            <div className="alignment-changes">
              <strong>声称改动:</strong>
              {diff.revision_alignment.claimed_changes.join('; ')}
            </div>
          )}
          {diff.revision_alignment.actual_changes.length > 0 && (
            <div className="alignment-changes">
              <strong>实际变化:</strong>
              {diff.revision_alignment.actual_changes
                .map(
                  (c) =>
                    `${c.category}: ${c.change_type}${
                      c.change_type === 'modified'
                        ? `(${c.old_value}→${c.new_value})`
                        : ''
                    }`,
                )
                .join('; ')}
            </div>
          )}
        </div>
      )}

      {/* 统计栏 */}
      {stats && stats.total_comparisons > 0 && (
        <div className="vdiff-stats-bar">
          <span>共 {stats.total_comparisons} 项对比</span>
          <span style={{ color: '#1e8e3e' }}>已解决 {stats.resolved_count}</span>
          <span style={{ color: '#e37400' }}>缓解 {stats.mitigated_count}</span>
          <span style={{ color: '#d93025' }}>仍存在 {stats.persists_count}</span>
          <span style={{ color: '#d93025' }}>新问题 {stats.new_issue_count}</span>
          {stats.manual_labels > 0 && (
            <span>已解决精确率 {(stats.resolved_precision * 100).toFixed(0)}%</span>
          )}
        </div>
      )}

      {message && <div className="vdiff-message">{message}</div>}

      {/* 五态分组展示 */}
      {statusOrder.map((status) => {
        const items = grouped[status]
        if (!items || items.length === 0) return null
        return (
          <div key={status} className="vdiff-section">
            <h4>
              {VDIFF_STATUS_LABELS[status]}({items.length})
            </h4>
            {items.map((c) => (
              <div key={c.comparison_id} className="vdiff-card">
                <div className="vdiff-card-header">
                  <span
                    className="vdiff-status-tag"
                    style={{
                      color: VDIFF_STATUS_COLORS[c.status],
                      borderColor: VDIFF_STATUS_COLORS[c.status],
                    }}
                  >
                    {VDIFF_STATUS_LABELS[c.status]}
                  </span>
                  {c.old_level && c.new_level && c.old_level !== c.new_level && (
                    <span className="vdiff-level-change">
                      {c.old_level} → {c.new_level}
                    </span>
                  )}
                </div>
                <div className="vdiff-reason">{c.reason}</div>
                <div className="vdiff-identity">
                  <span className="identity-tag">
                    规则:{c.identity.rule_id}
                  </span>
                  <span className="identity-tag">
                    问题类别:{c.identity.problem_category}
                  </span>
                  {c.identity.evidence_categories.length > 0 && (
                    <span className="identity-tag">
                      证据范围:{c.identity.evidence_categories.join(', ')}
                    </span>
                  )}
                </div>

                {/* 人工复核标签(仅 resolved/mitigated/persists 显示) */}
                {(c.status === 'resolved' ||
                  c.status === 'mitigated' ||
                  c.status === 'persists') &&
                  !labeledIds.has(c.comparison_id) && (
                    <div className="vdiff-label-actions">
                      <span className="label-prompt">人工验证:</span>
                      <button
                        className="btn-small"
                        onClick={() => handleLabel(c.comparison_id, 'resolved')}
                      >
                        确认已解决
                      </button>
                      <button
                        className="btn-small"
                        onClick={() => handleLabel(c.comparison_id, 'persists')}
                      >
                        实际仍存在
                      </button>
                    </div>
                  )}
                {labeledIds.has(c.comparison_id) && (
                  <div className="vdiff-labeled">已标注</div>
                )}
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
