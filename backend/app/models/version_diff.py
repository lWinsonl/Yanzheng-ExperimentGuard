"""版本差异复审与学习迁移评估模型(P2)。

差异化:同时解决"问题是否真的被修复"和"学生能否把方法迁移到新实验"。

设计要点:
1. 发现稳定身份:rule_id + 主张 + 证据范围 + 问题类别组合哈希,
   不只按 rule_id 配对——同一规则在不同主张/证据上触发算不同问题。
2. 版本差异五态:已解决 / 缓解 / 仍存在 / 新问题 / 证据不足,每态附理由。
3. 修改理由对照:学生说改了什么 vs 事实层面实际改了什么。
4. 迁移题:不同表面情境、同一方法要点;评分看推理过程而非只看答案。
5. 人工复核标签:验证"已解决"精确率与迁移表现。
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, Field

from app.models.evidence import new_id


class VersionDiffStatus(str, Enum):
    """版本差异五态。"""

    RESOLVED = "resolved"                    # 已解决:旧发现不再触发
    MITIGATED = "mitigated"                  # 缓解:仍触发但严重度降低
    PERSISTS = "persists"                    # 仍存在:同级别或更严重
    NEW_ISSUE = "new_issue"                  # 新问题:新报告中新出现的
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # 证据不足:无法判定


class RevisionAlignmentLevel(str, Enum):
    """修改理由与实际变化的对照结果。"""

    ALIGNED = "aligned"              # 理由与实际变化一致
    PARTIALLY_ALIGNED = "partially_aligned"  # 部分一致
    NOT_ALIGNED = "not_aligned"      # 不一致(声称改了但实际没变,或反之)
    UNKNOWN = "unknown"              # 缺少旧版快照，无法核对


class MigrationScoreDimension(str, Enum):
    """迁移题评分维度(看推理过程而非只看答案)。"""

    IDENTIFIES_CORE_ISSUE = "identifies_core_issue"  # 是否识别出核心方法问题
    EXPLAINS_WHY = "explains_why"                    # 是否解释了为什么这是问题
    PROPOSES_FIX = "proposes_fix"                    # 是否给出正确修改方向
    REASONING_QUALITY = "reasoning_quality"          # 推理过程质量(逻辑链完整性)


class FindingIdentity(BaseModel):
    """发现的稳定身份:跨报告可追踪同一问题。

    组成:rule_id + 主张ID集合 + 证据类别集合 + 问题类别。
    同一规则在不同主张/证据上触发 → 不同身份;
    同一问题在前后两份报告中 → 相同身份(即使 finding_id 变了)。
    """

    identity_hash: str
    """身份哈希(确定性,由组件拼接后 SHA-256 前16位)。"""

    rule_id: str
    claim_ids: list[str] = Field(default_factory=list)
    evidence_categories: list[str] = Field(default_factory=list)
    """证据范围:涉及的 FactCategory 值集合(如 data_split+metric)。"""

    problem_category: str = ""
    issue_scope: str | None = None
    """问题类别:从 rule_id 推断的问题类型(如 split_inconsistency)。"""

    @staticmethod
    def compute(
        rule_id: str,
        claim_ids: list[str],
        evidence_categories: list[str],
        problem_category: str = "",
        issue_scope: str | None = None,
    ) -> "FindingIdentity":
        """确定性计算身份哈希:组件排序后拼接,SHA-256 取前16位。"""
        raw = "|".join([
            rule_id,
            ",".join(sorted(claim_ids)),
            ",".join(sorted(evidence_categories)) if issue_scope is None else issue_scope,
            problem_category or rule_id,
        ])
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return FindingIdentity(
            identity_hash=h,
            rule_id=rule_id,
            claim_ids=sorted(claim_ids),
            evidence_categories=sorted(evidence_categories),
            problem_category=problem_category or rule_id,
            issue_scope=issue_scope,
        )


class VersionDiffComparison(BaseModel):
    """单条发现的前后版本对比(五态)。"""

    comparison_id: str = Field(default_factory=lambda: new_id("vdiff"))
    old_finding_id: str = ""
    identity: FindingIdentity
    status: VersionDiffStatus
    reason: str
    """判定理由,如"修改后按设备划分,该矛盾不再触发"。"""

    old_level: str = ""
    new_level: str = ""
    """前后严重度(缓解时展示降级路径)。"""

    new_finding_id: str = ""
    """若仍触发(PERSISTS/MITIGATED),指向新报告中的对应发现。"""


class FactChange(BaseModel):
    """单条事实的版本变化。"""

    category: str
    old_value: str = ""
    new_value: str = ""
    change_type: str = ""
    """added / removed / modified / unchanged。"""


class RevisionAlignment(BaseModel):
    """修改理由与实际变化对照:学生说改了什么 vs 事实层面实际改了什么。"""

    revision_note: str = ""
    """学生提交的修改理由原文。"""

    claimed_changes: list[str] = Field(default_factory=list)
    """从修改理由中提取的声称改动(如"改为按设备划分")。"""

    actual_changes: list[FactChange] = Field(default_factory=list)
    """事实层面的实际变化。"""

    alignment: RevisionAlignmentLevel = RevisionAlignmentLevel.NOT_ALIGNED
    alignment_detail: str = ""
    """对照说明,如"声称改了划分方式,事实层面 data_split 确实从记录级变为设备级"。"""


class VersionDiffResult(BaseModel):
    """完整的版本差异复审结果。"""

    diff_id: str = Field(default_factory=lambda: new_id("vdiff_result"))
    session_id: str
    old_report_id: str
    new_report_id: str
    comparisons: list[VersionDiffComparison] = Field(default_factory=list)
    new_issue_ids: list[str] = Field(default_factory=list)
    """新问题对应的 comparison_id 列表。"""

    revision_alignment: RevisionAlignment = Field(default_factory=RevisionAlignment)
    created_at: str = ""


class MigrationQuestion(BaseModel):
    """迁移题:不同表面情境、同一方法要点。

    评分看推理过程:学生是否识别核心问题、是否解释为什么、是否给出正确修改方向。
    """

    question_id: str = Field(default_factory=lambda: new_id("mig"))
    session_id: str
    source_finding_id: str = ""
    """基于哪条原发现生成。"""

    source_rule_id: str = ""
    """对应的方法要点(规则)。"""

    method_point: str = ""
    """核心方法要点,如"泛化主张需按组划分防数据泄漏"。"""

    scenario: str = ""
    """新情境描述(表面不同但方法要点相同)。"""

    question: str = ""
    """让学生思考的问题。"""

    hint: str = ""
    reference_answer: str = ""
    """参考思路(学生作答后才展示)。"""

    created_at: str = ""


class MigrationAnswer(BaseModel):
    """迁移题回答与评分(推理过程评分)。"""

    answer_id: str = Field(default_factory=lambda: new_id("miga"))
    question_id: str
    session_id: str
    answer_text: str = ""
    answered_at: str = ""

    # 推理过程评分(各维度 0-1)
    identifies_core_issue: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    explains_why: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    proposes_fix: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    reasoning_quality: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    total_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    """四维平均(0-1)。"""

    feedback: str = ""
    """评分反馈:指出推理中的亮点与不足。"""

    source: str = "heuristic"
    """heuristic / llm。"""

    score_status: str = "legacy_unverified"
    """model_feedback / feedback_only / legacy_unverified；单次模型反馈不证明掌握。"""


class ManualReviewLabel(BaseModel):
    """人工复核标签:验证"已解决"判定的精确率。"""

    label_id: str = Field(default_factory=lambda: new_id("mlbl"))
    comparison_id: str
    actual_status: VersionDiffStatus
    """人工判定的真实状态。"""

    labeled_by: str = ""
    labeled_at: str = ""
    note: str = ""


class VersionDiffStats(BaseModel):
    """版本差异复审与迁移评估统计(验证指标)。

    - 已解决精确率:系统判定 resolved 且人工也确认 resolved 的比例。
    - 迁移表现:平均分、通过率(total_score >= 0.6)。
    """

    total_comparisons: int = 0
    resolved_count: int = 0
    mitigated_count: int = 0
    persists_count: int = 0
    new_issue_count: int = 0
    insufficient_evidence_count: int = 0

    manual_labels: int = 0
    resolved_precision: float = 0.0
    """已解决精确率 = 人工确认 resolved / 系统判定 resolved(有标签时)。"""

    migration_total: int = 0
    migration_avg_score: float = 0.0
    migration_pass_rate: float = 0.0
    """迁移通过率 = total_score >= 0.6 的比例。"""

    revision_aligned_rate: float = 0.0
    """修改理由与实际变化一致率。"""
