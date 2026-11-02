// API 客户端:所有请求经 Vite 代理转发到后端
import type {
  AgentStatus,
  ClaimEvidenceEdge,
  ClaimGraph,
  DeepReviewResult,
  DirectionAnalysis,
  ExperimentType,
  ExtractedFact,
  Followup,
  FollowupQuestion,
  FollowupStats,
  GapAnalysis,
  IngestResponse,
  ManualReviewLabel,
  MaterialMeta,
  MaterialRole,
  MigrationAnswer,
  MigrationQuestion,
  ParsedDocument,
  RecheckResult,
  ReviewReport,
  ReviewSession,
  SubClaim,
  TeachingCase,
  VersionDiffResult,
  VersionDiffStats,
} from '../types'

const BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail || `请求失败:${res.status}`)
  }
  return res.json() as Promise<T>
}

// ---- 会话 ----
export function createSession(
  title: string,
  experiment_type: ExperimentType,
  claims: string[],
): Promise<ReviewSession> {
  return request('/sessions', {
    method: 'POST',
    body: JSON.stringify({ title, experiment_type, claims }),
  })
}

export function getSession(sessionId: string): Promise<ReviewSession> {
  return request(`/sessions/${sessionId}`)
}

export function listSessions(): Promise<ReviewSession[]> {
  return request('/sessions')
}

export function listMaterials(sessionId: string): Promise<MaterialMeta[]> {
  return request(`/sessions/${sessionId}/materials`)
}

export function getMaterialContent(
  sessionId: string,
  materialId: string,
): Promise<ParsedDocument> {
  return request(`/sessions/${sessionId}/materials/${materialId}`)
}

// ---- 材料 ----
export async function uploadFile(
  sessionId: string,
  role: MaterialRole,
  file: File,
  mode: 'append' | 'replace' = 'append',
): Promise<IngestResponse> {
  const form = new FormData()
  form.append('role', role)
  form.append('mode', mode)
  form.append('file', file)
  const res = await fetch(`${BASE}/sessions/${sessionId}/materials/upload`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail || '上传失败')
  }
  return res.json()
}

export function addTextMaterial(
  sessionId: string,
  role: MaterialRole,
  filename: string,
  content: string,
  mode: 'append' | 'replace' = 'append',
): Promise<IngestResponse> {
  return request(`/sessions/${sessionId}/materials/text`, {
    method: 'POST',
    body: JSON.stringify({ role, filename, content, mode }),
  })
}

// ---- 事实 ----
export function listFacts(
  sessionId: string,
  status?: string,
): Promise<ExtractedFact[]> {
  const q = status ? `?status=${status}` : ''
  return request(`/sessions/${sessionId}/facts${q}`)
}

export function confirmFact(
  sessionId: string,
  factId: string,
  action: 'confirm' | 'correct' | 'reject',
  correctedValue?: string,
): Promise<ExtractedFact> {
  return request(`/sessions/${sessionId}/facts/${factId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ action, corrected_value: correctedValue ?? null }),
  })
}

export function confirmAllPending(sessionId: string): Promise<{
  confirmed_count: number
  facts: ExtractedFact[]
}> {
  return request(`/sessions/${sessionId}/facts/confirm-all`, { method: 'POST' })
}

// ---- 审查 ----
export function runReview(sessionId: string): Promise<ReviewReport> {
  return request(`/sessions/${sessionId}/review/run`, { method: 'POST' })
}

export function getLatestReport(sessionId: string): Promise<ReviewReport> {
  return request(`/sessions/${sessionId}/review/latest`)
}

// ---- 复查 ----
export function runRecheck(
  sessionId: string,
  revisionNote: string,
): Promise<RecheckResult> {
  return request(`/sessions/${sessionId}/recheck/run`, {
    method: 'POST',
    body: JSON.stringify({ revision_note: revisionNote }),
  })
}

// ---- 智能体 ----
export function getAgentStatus(sessionId: string): Promise<AgentStatus> {
  return request(`/sessions/${sessionId}/agent/status`)
}

export function analyzeDirection(sessionId: string): Promise<DirectionAnalysis> {
  return request(`/sessions/${sessionId}/agent/direction`, { method: 'POST' })
}

export function analyzeGaps(sessionId: string): Promise<GapAnalysis> {
  return request(`/sessions/${sessionId}/agent/gaps`, { method: 'POST' })
}

export function generateFollowups(
  sessionId: string,
): Promise<{ followups: Followup[] }> {
  return request(`/sessions/${sessionId}/agent/followups`, { method: 'POST' })
}

export function deepReview(sessionId: string): Promise<DeepReviewResult> {
  return request(`/sessions/${sessionId}/agent/deep-review`, { method: 'POST' })
}

export function generateTeachingCase(
  sessionId: string,
): Promise<TeachingCase> {
  return request(`/sessions/${sessionId}/agent/teaching-case`, { method: 'POST' })
}

// ---- 主张-证据图 ----
export function buildClaimGraph(sessionId: string): Promise<ClaimGraph> {
  return request(`/sessions/${sessionId}/claim-graph/build`, { method: 'POST' })
}

export function getClaimGraph(sessionId: string): Promise<ClaimGraph> {
  return request(`/sessions/${sessionId}/claim-graph`)
}

export function confirmGraphEdge(
  sessionId: string,
  edgeId: string,
  action: 'confirm' | 'correct' | 'reject',
  correctedRelation?: 'supports' | 'contradicts' | 'unknown',
): Promise<ClaimEvidenceEdge> {
  return request(`/sessions/${sessionId}/claim-graph/edges/${edgeId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({
      action,
      corrected_relation: correctedRelation ?? null,
    }),
  })
}

export function confirmGraphSubClaim(
  sessionId: string,
  subClaimId: string,
  action: 'confirm' | 'reject',
): Promise<SubClaim> {
  return request(
    `/sessions/${sessionId}/claim-graph/sub-claims/${subClaimId}/confirm`,
    { method: 'POST', body: JSON.stringify({ action }) },
  )
}

export function proposeGraphCandidates(
  sessionId: string,
): Promise<{
  status: string
  message: string
  added: number
  candidate_sub_claims?: number
  candidate_edges?: number
}> {
  return request(`/sessions/${sessionId}/claim-graph/candidates`, {
    method: 'POST',
  })
}

// ---- 主动追问(P1:基于预期信息价值) ----
export function generateRankedFollowups(
  sessionId: string,
): Promise<{
  status: string
  message: string
  questions: FollowupQuestion[]
  source: string
}> {
  return request(`/sessions/${sessionId}/followups/generate`, { method: 'POST' })
}

export function listFollowups(
  sessionId: string,
): Promise<{ questions: FollowupQuestion[] }> {
  return request(`/sessions/${sessionId}/followups`)
}

export function answerFollowup(
  sessionId: string,
  questionId: string,
  answerText: string,
): Promise<FollowupQuestion> {
  return request(`/sessions/${sessionId}/followups/${questionId}/answer`, {
    method: 'POST',
    body: JSON.stringify({ answer_text: answerText }),
  })
}

export function skipFollowup(
  sessionId: string,
  questionId: string,
): Promise<FollowupQuestion> {
  return request(`/sessions/${sessionId}/followups/${questionId}/skip`, {
    method: 'POST',
  })
}

export function reviewFollowupAnswer(sessionId: string, questionId: string): Promise<FollowupQuestion> {
  return request(`/sessions/${sessionId}/followups/${questionId}/review`, { method: 'POST' })
}

export function getFollowupStats(
  sessionId: string,
): Promise<FollowupStats> {
  return request(`/sessions/${sessionId}/followups/stats`)
}

// ---- 版本差异复审与学习迁移评估(P2) ----
export function runVersionDiff(
  sessionId: string,
  revisionNote: string,
): Promise<VersionDiffResult> {
  return request(`/sessions/${sessionId}/version-diff/run`, {
    method: 'POST',
    body: JSON.stringify({ revision_note: revisionNote }),
  })
}

export function getLatestVersionDiff(
  sessionId: string,
): Promise<VersionDiffResult> {
  return request(`/sessions/${sessionId}/version-diff`)
}

export function addManualLabel(
  sessionId: string,
  comparisonId: string,
  actualStatus: string,
  labeledBy: string = '',
  note: string = '',
): Promise<ManualReviewLabel> {
  return request(`/sessions/${sessionId}/version-diff/labels`, {
    method: 'POST',
    body: JSON.stringify({
      comparison_id: comparisonId,
      actual_status: actualStatus,
      labeled_by: labeledBy,
      note,
    }),
  })
}

export function getVersionDiffStats(
  sessionId: string,
): Promise<VersionDiffStats> {
  return request(`/sessions/${sessionId}/version-diff/stats`)
}

export function generateMigrationQuestion(
  sessionId: string,
): Promise<{
  status: string
  message: string
  question: MigrationQuestion | null
  source?: string
}> {
  return request(`/sessions/${sessionId}/migration/generate`, { method: 'POST' })
}

export function listMigrationQuestions(
  sessionId: string,
): Promise<{ questions: MigrationQuestion[]; answers: MigrationAnswer[] }> {
  return request(`/sessions/${sessionId}/migration`)
}

export function answerMigration(
  sessionId: string,
  questionId: string,
  answerText: string,
): Promise<{
  status: string
  message: string
  answer: MigrationAnswer | null
}> {
  return request(`/sessions/${sessionId}/migration/${questionId}/answer`, {
    method: 'POST',
    body: JSON.stringify({ answer_text: answerText }),
  })
}
