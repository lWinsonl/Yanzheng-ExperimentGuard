// 与后端 app/models 对应的类型定义

export type MaterialRole = 'plan' | 'execution'
export type MaterialKind = 'text' | 'code' | 'config' | 'result' | 'pdf'
export type FactCategory =
  | 'comparison_target'
  | 'data_split'
  | 'metric'
  | 'baseline'
  | 'repetition'
  | 'dataset_desc'
  | 'claim_scope'
  | 'other'
export type FactStatus = 'pending_user_confirm' | 'confirmed' | 'corrected' | 'rejected'
export type FindingLevel = 'contradiction' | 'risk' | 'insufficient'
export type ExperimentType = 'data_model' | 'algorithm_system'

/** 原文位置锚点:证据链最底层 */
export interface SourceSpan {
  material_id: string
  start_char: number
  end_char: number
  snippet: string
}

/** 解析后的文档 */
export interface ParsedDocument {
  material_id: string
  role: MaterialRole
  kind: MaterialKind
  filename: string
  content: string
  ocr_required: boolean
  ocr_note: string
}

/** 带出处的可核对事实 */
export interface ExtractedFact {
  fact_id: string
  session_id: string
  category: FactCategory
  value: string
  source: SourceSpan
  extraction_source: 'rule' | 'llm'
  status: FactStatus
  corrected_value: string | null
  note: string
  created_at: string
}

/** 研究主张 */
export interface Claim {
  claim_id: string
  text: string
  scope_keywords: string[]
  experiment_type: ExperimentType
}

/** 审查会话 */
export interface ReviewSession {
  session_id: string
  title: string
  experiment_type: ExperimentType
  claims: Claim[]
  material_ids: string[]
  created_at: string
}

/** 证据引用(发现中携带事实值与原文片段) */
export interface EvidenceRef {
  fact_id: string
  category: FactCategory
  value: string
  source: SourceSpan
}

/** 一条审查发现 */
export interface Finding {
  finding_id: string
  rule_id: string
  level: FindingLevel
  title: string
  claim_ids: string[]
  evidence: EvidenceRef[]
  missing_evidence: string[]
  suggestion: string
  suggestion_type: 'fix' | 'narrow' | 'clarify'
  reasoning: string
}

/** 审查报告 */
export interface ReviewReport {
  report_id: string
  session_id: string
  findings: Finding[]
  usable_fact_count: number
  skipped_fact_count: number
  created_at: string
}

/** 复查对比项 */
export interface RecheckComparison {
  finding_id: string
  rule_id: string
  title: string
  resolved: boolean
  new_finding_id: string | null
  note: string
}

/** 复查结果 */
export interface RecheckResult {
  recheck_id: string
  session_id: string
  old_report_id: string
  new_report_id: string
  comparisons: RecheckComparison[]
  newly_raised: string[]
  revision_note: string
}

/** 材料元信息(列表用,不含全文) */
export interface MaterialMeta {
  material_id: string
  role: MaterialRole
  kind: MaterialKind
  filename: string
  content_length: number
  ocr_required: boolean
  ocr_note: string
}

/** 上传/粘贴材料的响应 */
export interface IngestResponse {
  material_id: string
  filename: string
  role: MaterialRole
  kind: MaterialKind
  ocr_required: boolean
  ocr_note: string
  extracted_facts: ExtractedFact[]
  dropped: string[]
}

export const CATEGORY_LABELS: Record<FactCategory, string> = {
  comparison_target: '比较对象',
  data_split: '数据划分',
  metric: '评价指标',
  baseline: '基线方法',
  repetition: '重复运行',
  dataset_desc: '数据集描述',
  claim_scope: '主张范围',
  other: '其他',
}

export const LEVEL_LABELS: Record<FindingLevel, string> = {
  contradiction: '明确矛盾',
  risk: '潜在风险',
  insufficient: '信息不足',
}

export const LEVEL_COLORS: Record<FindingLevel, string> = {
  contradiction: '#d93025',
  risk: '#e37400',
  insufficient: '#1a73e8',
}

export const STATUS_LABELS: Record<FactStatus, string> = {
  pending_user_confirm: '待确认',
  confirmed: '已确认',
  corrected: '已纠正',
  rejected: '已拒绝',
}

// ---- 智能体相关类型 ----

export interface AgentStatus {
  llm_available: boolean
  mode: 'llm' | 'heuristic'
  note: string
}

export interface DirectionAnalysis {
  claim_clarity: string
  clarity_note: string
  design_requirements: { requirement: string; reason: string; linked_claim_keyword: string }[]
  direction_issues: { issue: string; severity: string; explanation: string }[]
  source: 'heuristic' | 'llm'
}

export interface GapAnalysis {
  sufficiency: string
  gaps: { missing: string; priority: string; reason: string; how_to_provide: string }[]
  summary: string
  source: 'heuristic' | 'llm'
}

export interface Followup {
  target_finding: string
  question: string
  what_to_provide: string
  why_needed: string
}

export interface DeepFinding {
  level: FindingLevel
  title: string
  reasoning: string
  verified_quote: string
  material_filename: string
  suggestion: string
  suggestion_type: string
  quote_verified: boolean
  suggestion_action?: string
  suggestion_reason?: string
  suggestion_verify?: string
}

export interface TeachingCase {
  case_title: string
  case_description: string
  question: string
  hint: string
  reference_answer: string
  related_rule: string
  source: 'preset' | 'llm'
}