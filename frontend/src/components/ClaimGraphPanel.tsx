import { useCallback, useEffect, useState } from 'react'
import type {
  ClaimEvidenceEdge,
  ClaimGraph,
  CounterEvidenceCheck,
  EdgeRelation,
  ExtractedFact,
  SubClaim,
} from '../types'
import {
  ASPECT_LABELS,
  COUNTER_STATUS_COLORS,
  COUNTER_STATUS_LABELS,
  DIRECTION_LABELS,
  EDGE_STATUS_LABELS,
  RELATION_COLORS,
  RELATION_LABELS,
} from '../types'
import {
  buildClaimGraph,
  confirmGraphEdge,
  confirmGraphSubClaim,
  getClaimGraph,
  listFacts,
  proposeGraphCandidates,
} from '../api'

interface Props {
  sessionId: string
  claimTexts: Record<string, string>
  onGraphChange?: (graph: ClaimGraph | null) => void
}

/** 主张-证据图面板:把主张拆成可检验子主张,与证据显式连接,支持逐条校准。
 * 核心差异化:每条边说明支持/矛盾/未知及其依据;反证检查区分"没找到"与"证明不存在"。
 */
export function ClaimGraphPanel({ sessionId, claimTexts, onGraphChange }: Props) {
  const [graph, setGraph] = useState<ClaimGraph | null>(null)
  const [facts, setFacts] = useState<Record<string, ExtractedFact>>({})
  const [busy, setBusy] = useState(false)
  const [candidateMsg, setCandidateMsg] = useState('')
  const [expandedClaims, setExpandedClaims] = useState<Set<string>>(new Set())
  const [expandedSubs, setExpandedSubs] = useState<Set<string>>(new Set())

  const loadGraph = useCallback(async () => {
    try {
      const g = await getClaimGraph(sessionId)
      setGraph(g)
      const allFacts = await listFacts(sessionId)
      const map: Record<string, ExtractedFact> = {}
      allFacts.forEach((f) => (map[f.fact_id] = f))
      setFacts(map)
    } catch {
      setGraph(null)
    }
  }, [sessionId])

  useEffect(() => {
    let active = true
    Promise.all([getClaimGraph(sessionId), listFacts(sessionId)]).then(([value, items]) => {
      if (!active) return
      setGraph(value)
      setFacts(Object.fromEntries(items.map((fact) => [fact.fact_id, fact])))
      setExpandedClaims(new Set(value.sub_claims.map((sc) => sc.claim_id)))
    }).catch(() => { if (active) setGraph(null) })
    return () => { active = false }
  }, [sessionId])

  // 图变化时通知父组件(用于导出 Markdown)
  useEffect(() => {
    onGraphChange?.(graph)
  }, [graph, onGraphChange])

  async function build() {
    setBusy(true)
    try {
      const g = await buildClaimGraph(sessionId)
      setGraph(g)
      // 默认展开所有主张
      setExpandedClaims(new Set(g.sub_claims.map((sc) => sc.claim_id)))
      const allFacts = await listFacts(sessionId)
      const map: Record<string, ExtractedFact> = {}
      allFacts.forEach((f) => (map[f.fact_id] = f))
      setFacts(map)
    } finally {
      setBusy(false)
    }
  }

  async function handleEdgeAction(
    edge: ClaimEvidenceEdge,
    action: 'confirm' | 'correct' | 'reject',
    correctedRelation?: EdgeRelation,
  ) {
    const updated = await confirmGraphEdge(
      sessionId, edge.edge_id, action, correctedRelation,
    )
    setGraph((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        edges: prev.edges.map((e) =>
          e.edge_id === updated.edge_id ? updated : e,
        ),
      }
    })
  }

  async function handleSubClaimAction(
    sc: SubClaim,
    action: 'confirm' | 'reject',
  ) {
    const updated = await confirmGraphSubClaim(sessionId, sc.sub_claim_id, action)
    setGraph((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        sub_claims: prev.sub_claims.map((s) =>
          s.sub_claim_id === updated.sub_claim_id ? updated : s,
        ),
        // 拒绝子主张时级联拒绝其下所有边
        edges:
          action === 'reject'
            ? prev.edges.map((e) =>
                e.sub_claim_id === updated.sub_claim_id
                  ? { ...e, status: 'rejected' as const }
                  : e,
              )
            : prev.edges,
      }
    })
  }

  async function proposeCandidates() {
    setBusy(true)
    setCandidateMsg('')
    try {
      const res = await proposeGraphCandidates(sessionId)
      setCandidateMsg(res.message)
      if (res.added > 0) await loadGraph()
    } catch (e) {
      setCandidateMsg(e instanceof Error ? e.message : '候选边提案失败')
    } finally {
      setBusy(false)
    }
  }

  function toggleClaim(claimId: string) {
    setExpandedClaims((prev) => {
      const next = new Set(prev)
      if (next.has(claimId)) next.delete(claimId)
      else next.add(claimId)
      return next
    })
  }

  function toggleSub(subId: string) {
    setExpandedSubs((prev) => {
      const next = new Set(prev)
      if (next.has(subId)) next.delete(subId)
      else next.add(subId)
      return next
    })
  }

  if (!graph) {
    return (
      <div className="claim-graph-panel">
        <div className="agent-section-header">
          <span>🔗 主张-证据图</span>
        </div>
        <p className="muted">
          把主张拆成可检验子主张,与计划、执行、结果、反证和缺失前提显式连接。
          每条边说明支持/矛盾/未知及其依据,反证检查区分"没找到反证"与"证明不存在反证"。
        </p>
        <button onClick={build} disabled={busy}>
          {busy ? '构建中…' : '构建主张-证据图'}
        </button>
      </div>
    )
  }

  const claimIds = [...new Set(graph.sub_claims.map((sc) => sc.claim_id))]
  const activeEdges = graph.edges.filter((e) => e.status !== 'rejected')
  const sCount = activeEdges.filter((e) => (e.corrected_relation ?? e.relation) === 'supports').length
  const cCount = activeEdges.filter((e) => (e.corrected_relation ?? e.relation) === 'contradicts').length
  const uCount = activeEdges.filter((e) => (e.corrected_relation ?? e.relation) === 'unknown').length

  return (
    <div className="claim-graph-panel">
      <div className="agent-section-header">
        <span>🔗 主张-证据图</span>
        <span className="graph-stats">
          支持 {sCount} · 矛盾 {cCount} · 未知 {uCount}
        </span>
      </div>

      <div className="graph-toolbar">
        <button onClick={build} disabled={busy}>
          {busy ? '重建中…' : '重建图'}
        </button>
        <button onClick={proposeCandidates} disabled={busy}>
          让模型补充候选边
        </button>
        {candidateMsg && <span className="muted candidate-msg">{candidateMsg}</span>}
      </div>

      {claimIds.map((claimId) => {
        const claimText = claimTexts[claimId] ?? claimId
        const subs = graph.sub_claims.filter(
          (sc) => sc.claim_id === claimId && sc.status !== 'rejected',
        )
        const expanded = expandedClaims.has(claimId)
        return (
          <div key={claimId} className="graph-claim">
            <div
              className="graph-claim-header"
              onClick={() => toggleClaim(claimId)}
            >
              <span className="toggle-icon">{expanded ? '▼' : '▶'}</span>
              <span className="claim-text">{claimText}</span>
              <span className="muted">{subs.length} 个子主张</span>
            </div>

            {expanded && (
              <div className="graph-sub-claims">
                {subs.map((sc) => (
                  <SubClaimNode
                    key={sc.sub_claim_id}
                    subClaim={sc}
                    graph={graph}
                    facts={facts}
                    expanded={expandedSubs.has(sc.sub_claim_id)}
                    onToggle={() => toggleSub(sc.sub_claim_id)}
                    onEdgeAction={handleEdgeAction}
                    onSubClaimAction={handleSubClaimAction}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---- 子主张节点 ----

interface SubClaimNodeProps {
  subClaim: SubClaim
  graph: ClaimGraph
  facts: Record<string, ExtractedFact>
  expanded: boolean
  onToggle: () => void
  onEdgeAction: (
    edge: ClaimEvidenceEdge,
    action: 'confirm' | 'correct' | 'reject',
    correctedRelation?: EdgeRelation,
  ) => void
  onSubClaimAction: (sc: SubClaim, action: 'confirm' | 'reject') => void
}

function SubClaimNode({
  subClaim, graph, facts, expanded, onToggle, onEdgeAction, onSubClaimAction,
}: SubClaimNodeProps) {
  const edges = graph.edges.filter(
    (e) => e.sub_claim_id === subClaim.sub_claim_id && e.status !== 'rejected',
  )
  const check = graph.counter_checks.find(
    (cc) => cc.sub_claim_id === subClaim.sub_claim_id,
  )
  const isPending = subClaim.status === 'pending_user_confirm'

  return (
    <div className={`graph-sub-claim ${isPending ? 'is-candidate' : ''}`}>
      <div className="graph-sub-header" onClick={onToggle}>
        <span className="toggle-icon">{expanded ? '▼' : '▶'}</span>
        <span className="aspect-badge">{ASPECT_LABELS[subClaim.test_aspect]}</span>
        <span className="sub-text">{subClaim.text}</span>
        {isPending && (
          <span className="candidate-badge">模型候选·待确认</span>
        )}
        <span className="edge-count">{edges.length} 条边</span>
      </div>

      {isPending && (
        <div className="candidate-actions">
          <button className="small" onClick={() => onSubClaimAction(subClaim, 'confirm')}>
            确认此子主张
          </button>
          <button
            className="small danger"
            onClick={() => onSubClaimAction(subClaim, 'reject')}
          >
            拒绝
          </button>
        </div>
      )}

      {expanded && (
        <div className="graph-edges">
          {edges.length === 0 && (
            <div className="muted">暂无证据边</div>
          )}
          {edges.map((edge) => (
            <EdgeRow
              key={edge.edge_id}
              edge={edge}
              fact={edge.fact_id ? facts[edge.fact_id] : undefined}
              onAction={onEdgeAction}
            />
          ))}
          {check && <CounterCheckCard check={check} facts={facts} />}
        </div>
      )}
    </div>
  )
}

// ---- 边行 ----

function EdgeRow({
  edge, fact, onAction,
}: {
  edge: ClaimEvidenceEdge
  fact: ExtractedFact | undefined
  onAction: SubClaimNodeProps['onEdgeAction']
}) {
  const relation = edge.corrected_relation ?? edge.relation
  const color = RELATION_COLORS[relation]
  const isPending = edge.status === 'pending_user_confirm'
  const isCorrected = edge.status === 'corrected'

  return (
    <div className={`graph-edge ${isPending ? 'is-candidate' : ''}`}>
      <div className="edge-main">
        <span
          className="relation-tag"
          style={{ backgroundColor: color + '18', color, borderColor: color + '40' }}
        >
          {RELATION_LABELS[relation]}
        </span>
        <span className="direction-tag">{DIRECTION_LABELS[edge.direction]}</span>
        {edge.source === 'llm' && (
          <span className="candidate-badge">候选</span>
        )}
        {isCorrected && (
          <span className="corrected-badge">已纠正</span>
        )}
        <span className="edge-basis">{edge.basis}</span>
      </div>

      {fact && (
        <div className="edge-fact">
          <span className="fact-value">[{fact.category}] {fact.value}</span>
          {fact.source?.snippet && (
            <blockquote className="fact-snippet">
              "{fact.source.snippet.slice(0, 120)}
              {fact.source.snippet.length > 120 ? '…' : ''}"
            </blockquote>
          )}
        </div>
      )}

      {edge.direction === 'missing_premise' && !fact && (
        <div className="edge-fact">
          <span className="muted">ⓘ 缺失前提:无可绑定的已确认事实</span>
        </div>
      )}

      <div className="edge-actions">
        {isPending ? (
          <>
            <button className="small" onClick={() => onAction(edge, 'confirm')}>
              确认
            </button>
            <button
              className="small danger"
              onClick={() => onAction(edge, 'reject')}
            >
              拒绝
            </button>
          </>
        ) : (
          <>
            {edge.status !== 'corrected' && (
              <button
                className="small"
                onClick={() => onAction(edge, 'correct', relation === 'supports' ? 'contradicts' : 'supports')}
                title="切换支持/矛盾"
              >
                纠正为{relation === 'supports' ? '矛盾' : '支持'}
              </button>
            )}
            {edge.status !== 'rejected' && (
              <button
                className="small danger"
                onClick={() => onAction(edge, 'reject')}
              >
                拒绝此边
              </button>
            )}
          </>
        )}
        <span className="muted edge-status">
          {EDGE_STATUS_LABELS[edge.status]}
        </span>
      </div>
    </div>
  )
}

// ---- 反证检查卡片 ----

function CounterCheckCard({
  check, facts,
}: {
  check: CounterEvidenceCheck
  facts: Record<string, ExtractedFact>
}) {
  const color = COUNTER_STATUS_COLORS[check.proof_status]
  return (
    <div className="counter-check-card">
      <div className="counter-header">
        <span
          className="counter-status-tag"
          style={{ backgroundColor: color + '18', color, borderColor: color + '40' }}
        >
          {COUNTER_STATUS_LABELS[check.proof_status]}
        </span>
      </div>
      <div className="counter-alt">
        <strong>替代解释:</strong>{check.alternative_explanation}
      </div>
      <div className="counter-basis">
        <strong>判定依据:</strong>{check.basis}
      </div>
      {check.fact_ids.length > 0 && (
        <div className="counter-facts">
          <strong>支撑事实:</strong>
          {check.fact_ids.map((fid) => (
            <span key={fid} className="counter-fact-chip">
              {facts[fid]?.value ?? fid}
            </span>
          ))}
        </div>
      )}
      {check.missing_to_prove_absence.length > 0 && (
        <div className="counter-missing">
          <strong>升级为"证明不存在反证"还需:</strong>
          <ul>
            {check.missing_to_prove_absence.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}