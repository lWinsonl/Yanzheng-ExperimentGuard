// API 客户端:所有请求经 Vite 代理转发到后端
import type {
  AgentStatus,
  DeepFinding,
  DirectionAnalysis,
  ExperimentType,
  ExtractedFact,
  Followup,
  GapAnalysis,
  IngestResponse,
  MaterialMeta,
  MaterialRole,
  ParsedDocument,
  RecheckResult,
  ReviewReport,
  ReviewSession,
  TeachingCase,
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
): Promise<IngestResponse> {
  const form = new FormData()
  form.append('role', role)
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
): Promise<IngestResponse> {
  return request(`/sessions/${sessionId}/materials/text`, {
    method: 'POST',
    body: JSON.stringify({ role, filename, content }),
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

export function deepReview(
  sessionId: string,
): Promise<{ deep_findings: DeepFinding[] }> {
  return request(`/sessions/${sessionId}/agent/deep-review`, { method: 'POST' })
}

export function generateTeachingCase(
  sessionId: string,
): Promise<TeachingCase> {
  return request(`/sessions/${sessionId}/agent/teaching-case`, { method: 'POST' })
}