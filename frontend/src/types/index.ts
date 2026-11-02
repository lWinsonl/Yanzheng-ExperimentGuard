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

/** 单份材料的复核覆盖情况 */
export interface MaterialCoverage {
  material_id: string
  filename: string
  role: string
  total_chars: number
  checked_chars: number
  truncated: boolean
}

/** 模型复核状态:区分调用成功/失败/解析失败 */
export type DeepReviewStatus =
  | 'ok'
  | 'ok_no_findings'
  | 'llm_unavailable'
  | 'llm_call_failed'
  | 'llm_parse_failed'

/** 模型复核完整结果(含状态、发现、覆盖范围) */
export interface DeepReviewResult {
  status: DeepReviewStatus
  message: string
  findings: DeepFinding[]
  coverage: MaterialCoverage[]
  llm_available: boolean
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

// ---- 主张-证据图相关类型 ----

export type TestAspect =
  | 'scope'
  | 'comparison'
  | 'stability'
  | 'baseline_fairness'
  | 'metric_avail'

export type EdgeRelation = 'supports' | 'contradicts' | 'unknown'
export type EvidenceDirection =
  | 'plan'
  | 'execution'
  | 'result'
  | 'counter'
  | 'missing_premise'
export type EdgeSource = 'rule' | 'llm'
export type EdgeStatus =
  | 'pending_user_confirm'
  | 'confirmed'
  | 'corrected'
  | 'rejected'
export type CounterProofStatus =
  | 'no_counter_found'
  | 'counter_refuted'
  | 'counter_exists'

/** 可检验子主张 */
export interface SubClaim {
  sub_claim_id: string
  claim_id: string
  text: string
  test_aspect: TestAspect
  scope_keywords: string[]
  source: EdgeSource
  status: EdgeStatus
}

/** 主张-证据图中的一条边 */
export interface ClaimEvidenceEdge {
  edge_id: string
  sub_claim_id: string
  fact_id: string | null
  relation: EdgeRelation
  basis: string
  direction: EvidenceDirection
  scope: string
  source: EdgeSource
  status: EdgeStatus
  corrected_relation: EdgeRelation | null
}

/** 反证与替代解释检查 */
export interface CounterEvidenceCheck {
  check_id: string
  sub_claim_id: string
  alternative_explanation: string
  proof_status: CounterProofStatus
  basis: string
  fact_ids: string[]
  missing_to_prove_absence: string[]
}

/** 完整主张-证据图 */
export interface ClaimGraph {
  graph_id: string
  session_id: string
  sub_claims: SubClaim[]
  edges: ClaimEvidenceEdge[]
  counter_checks: CounterEvidenceCheck[]
  created_at: string
}

export const ASPECT_LABELS: Record<TestAspect, string> = {
  scope: '适用范围',
  comparison: '比较关系',
  stability: '稳定性',
  baseline_fairness: '基线公平',
  metric_avail: '指标可用',
}

export const RELATION_LABELS: Record<EdgeRelation, string> = {
  supports: '支持',
  contradicts: '矛盾',
  unknown: '未知',
}

export const RELATION_COLORS: Record<EdgeRelation, string> = {
  supports: '#1e8e3e',
  contradicts: '#d93025',
  unknown: '#5f6368',
}

export const DIRECTION_LABELS: Record<EvidenceDirection, string> = {
  plan: '计划材料',
  execution: '执行材料',
  result: '运行结果',
  counter: '反证方向',
  missing_premise: '缺失前提',
}

export const COUNTER_STATUS_LABELS: Record<CounterProofStatus, string> = {
  no_counter_found: '没有找到反证(不等于证明不存在)',
  counter_refuted: '反证已被排除(有直接证据)',
  counter_exists: '存在反证',
}

export const COUNTER_STATUS_COLORS: Record<CounterProofStatus, string> = {
  no_counter_found: '#e37400',
  counter_refuted: '#1e8e3e',
  counter_exists: '#d93025',
}

export const EDGE_STATUS_LABELS: Record<EdgeStatus, string> = {
  pending_user_confirm: '待确认',
  confirmed: '已确认',
  corrected: '已纠正',
  rejected: '已拒绝',
}

// ---- 主动追问(P1:基于预期信息价值) ----

export type EvidenceType =
  | 'code'
  | 'config'
  | 'result_data'
  | 'explanation'
  | 'split_record'
  | 'metric_value'

export type AnswerCost = 'low' | 'medium' | 'high'

export type FollowupStatus = 'pending' | 'answered' | 'skipped'

/** 基于预期信息价值排序的追问 */
export interface FollowupQuestion {
  question_id: string
  session_id: string
  target_finding_id: string
  target_finding_title: string
  sub_claim_id: string
  question: string
  what_to_provide: string
  why_needed: string
  evidence_type: EvidenceType
  evidence_format: string
  severity_score: number
  uncertainty: number
  change_probability: number
  cost_factor: number
  eiv_score: number
  score_explanation: string
  rank: number
  status: FollowupStatus
  answer_text: string
  answered_at: string
  answer_changed_finding: boolean
  finding_change_detail: string
  answer_material_id: string
  answer_fact_ids: string[]
  baseline_report_id: string
  review_state: 'not_reviewed' | 'awaiting_confirmation' | 'reviewed'
  created_at: string
}

/** 追问统计(离线比较用) */
export interface FollowupStats {
  total_questions: number
  answered: number
  skipped: number
  pending: number
  changed_findings: number
  completion_rate: number
  change_rate: number
  avg_questions: number
  avg_eiv_top: number
}

export const EVIDENCE_TYPE_LABELS: Record<EvidenceType, string> = {
  code: '代码片段',
  config: '配置文件',
  result_data: '运行结果数据',
  explanation: '文字说明',
  split_record: '数据划分记录',
  metric_value: '指标数值',
}

export const COST_LABELS: Record<AnswerCost, string> = {
  low: '低成本',
  medium: '中等成本',
  high: '高成本',
}

export const FOLLOWUP_STATUS_LABELS: Record<FollowupStatus, string> = {
  pending: '待回答',
  answered: '已回答',
  skipped: '已跳过',
}

// ---- 版本差异复审与学习迁移评估(P2) ----

export type VersionDiffStatus =
  | 'resolved'
  | 'mitigated'
  | 'persists'
  | 'new_issue'
  | 'insufficient_evidence'

export type RevisionAlignmentLevel = 'aligned' | 'partially_aligned' | 'not_aligned'

/** 发现稳定身份 */
export interface FindingIdentity {
  identity_hash: string
  rule_id: string
  claim_ids: string[]
  evidence_categories: string[]
  problem_category: string
}

/** 单条发现的前后版本对比(五态) */
export interface VersionDiffComparison {
  comparison_id: string
  old_finding_id: string
  identity: FindingIdentity
  status: VersionDiffStatus
  reason: string
  old_level: string
  new_level: string
  new_finding_id: string
}

/** 事实版本变化 */
export interface FactChange {
  category: string
  old_value: string
  new_value: string
  change_type: string
}

/** 修改理由与实际变化对照 */
export interface RevisionAlignment {
  revision_note: string
  claimed_changes: string[]
  actual_changes: FactChange[]
  alignment: RevisionAlignmentLevel
  alignment_detail: string
}

/** 完整版本差异复审结果 */
export interface VersionDiffResult {
  diff_id: string
  session_id: string
  old_report_id: string
  new_report_id: string
  comparisons: VersionDiffComparison[]
  new_issue_ids: string[]
  revision_alignment: RevisionAlignment
  created_at: string
}

/** 迁移题 */
export interface MigrationQuestion {
  question_id: string
  session_id: string
  source_finding_id: string
  source_rule_id: string
  method_point: string
  scenario: string
  question: string
  hint: string
  reference_answer: string
  created_at: string
}

/** 迁移题回答与评分 */
export interface MigrationAnswer {
  answer_id: string
  question_id: string
  session_id: string
  answer_text: string
  answered_at: string
  identifies_core_issue: number | null
  explains_why: number | null
  proposes_fix: number | null
  reasoning_quality: number | null
  total_score: number | null
  feedback: string
  source: string
  score_status: 'model_feedback' | 'feedback_only' | 'legacy_unverified'
}

/** 人工复核标签 */
export interface ManualReviewLabel {
  label_id: string
  comparison_id: string
  actual_status: VersionDiffStatus
  labeled_by: string
  labeled_at: string
  note: string
}

/** 版本差异统计 */
export interface VersionDiffStats {
  total_comparisons: number
  resolved_count: number
  mitigated_count: number
  persists_count: number
  new_issue_count: number
  insufficient_evidence_count: number
  manual_labels: number
  resolved_precision: number
  migration_total: number
  migration_avg_score: number
  migration_pass_rate: number
  revision_aligned_rate: number
}

export const VDIFF_STATUS_LABELS: Record<VersionDiffStatus, string> = {
  resolved: '已解决',
  mitigated: '缓解',
  persists: '仍存在',
  new_issue: '新问题',
  insufficient_evidence: '证据不足',
}

export const VDIFF_STATUS_COLORS: Record<VersionDiffStatus, string> = {
  resolved: '#1e8e3e',
  mitigated: '#e37400',
  persists: '#d93025',
  new_issue: '#d93025',
  insufficient_evidence: '#5f6368',
}

export const ALIGNMENT_LABELS: Record<RevisionAlignmentLevel, string> = {
  aligned: '一致',
  partially_aligned: '部分一致',
  not_aligned: '不一致',
}

export const ALIGNMENT_COLORS: Record<RevisionAlignmentLevel, string> = {
  aligned: '#1e8e3e',
  partially_aligned: '#e37400',
  not_aligned: '#d93025',
}
