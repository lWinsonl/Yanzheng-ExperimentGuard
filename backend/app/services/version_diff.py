"""版本差异复审与学习迁移评估服务(P2)。

核心差异化:
1. 发现稳定身份(不只按 rule_id):rule + 主张 + 证据范围 + 问题类别 → 哈希。
2. 版本差异五态:已解决/缓解/仍存在/新问题/证据不足,每态附理由。
3. 修改理由对照:学生声称的改动 vs 事实层面实际变化。
4. 迁移题评分:看推理过程(识别问题/解释原因/提出修改/推理质量)。
5. 人工复核标签:验证"已解决"精确率与迁移表现。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from app.models.evidence import FactCategory
from app.models.review import Finding, FindingLevel, ReviewReport
from app.models.version_diff import (
    FactChange,
    FindingIdentity,
    ManualReviewLabel,
    MigrationAnswer,
    MigrationQuestion,
    RevisionAlignment,
    RevisionAlignmentLevel,
    VersionDiffComparison,
    VersionDiffResult,
    VersionDiffStats,
    VersionDiffStatus,
)
from app.services.review import review_service
from app.services.store import data_store

logger = logging.getLogger("version_diff")

_SEVERITY_ORDER = {
    FindingLevel.CONTRADICTION: 2,
    FindingLevel.RISK: 1,
    FindingLevel.INSUFFICIENT: 0,
}

# 修改理由关键词 → 事实类别映射(用于提取声称改动)
_CLAIM_KEYWORDS: list[tuple[str, str]] = [
    ("划分", "data_split"), ("split", "data_split"), ("分组", "data_split"),
    ("泄漏", "data_split"), ("leak", "data_split"),
    ("基线", "baseline"), ("baseline", "baseline"), ("对比方法", "baseline"),
    ("重复", "repetition"), ("运行次数", "repetition"), ("多次", "repetition"),
    ("指标", "metric"), ("metric", "metric"), ("评价", "metric"),
    ("范围", "claim_scope"), ("收窄", "claim_scope"), ("主张", "claim_scope"),
]


class VersionDiffService:
    """版本差异复审:稳定身份配对、五态判定、修改理由对照、统计。"""

    # ---- 发现稳定身份 ----

    @staticmethod
    def compute_identity(finding: Finding) -> FindingIdentity:
        """为发现生成稳定身份:rule_id + 主张 + 证据范围 + 问题类别。"""
        evidence_cats = sorted({ref.category.value for ref in finding.evidence})
        # 问题类别:从 rule_id 提取主干(去序号后缀)
        problem_cat = re.sub(r"_\d+$", "", finding.rule_id)
        return FindingIdentity.compute(
            rule_id=finding.rule_id,
            claim_ids=finding.claim_ids,
            evidence_categories=evidence_cats,
            problem_category=problem_cat,
        )

    # ---- 版本差异计算(五态) ----

    def compute_diff(
        self,
        session_id: str,
        old_report: ReviewReport,
        new_report: ReviewReport,
        revision_note: str = "",
    ) -> VersionDiffResult:
        """计算前后报告的版本差异:按稳定身份配对,输出五态。"""
        store = data_store.require(session_id)
        current_fact_ids = set(store.facts.keys())

        # 旧发现的证据 fact_id 集合(用于判定证据是否消失)
        old_evidence_fact_ids: set[str] = set()
        for f in old_report.findings:
            old_evidence_fact_ids.update(ref.fact_id for ref in f.evidence)

        # 按身份哈希索引新发现
        new_by_identity: dict[str, list[Finding]] = {}
        for f in new_report.findings:
            ident = self.compute_identity(f)
            new_by_identity.setdefault(ident.identity_hash, []).append(f)

        comparisons: list[VersionDiffComparison] = []
        matched_new_ids: set[str] = set()

        # 遍历旧发现,判定 resolved / mitigated / persists / insufficient_evidence
        for old_f in old_report.findings:
            ident = self.compute_identity(old_f)
            matches = new_by_identity.get(ident.identity_hash, [])

            if not matches:
                # 身份未匹配:判断是已解决还是证据不足
                ev_ids = {ref.fact_id for ref in old_f.evidence}
                ev_gone = ev_ids - current_fact_ids  # 旧证据已消失
                ev_cats = {ref.category.value for ref in old_f.evidence}
                # 当前是否还有同类证据
                has_same_cat = any(
                    f.category.value in ev_cats for f in store.facts.values()
                )
                if ev_gone and not has_same_cat:
                    # 旧证据消失且无同类新证据:无法判定
                    comparisons.append(VersionDiffComparison(
                        old_finding_id=old_f.finding_id,
                        identity=ident,
                        status=VersionDiffStatus.INSUFFICIENT_EVIDENCE,
                        reason=(
                            f"原证据({'; '.join(ev_cats)})已被替换且无同类新证据,"
                            f"无法确认问题是否解决。请补充{'; '.join(ev_cats)}相关材料。"
                        ),
                        old_level=old_f.level.value,
                    ))
                else:
                    # 有同类新证据但规则不再触发 → 已解决
                    comparisons.append(VersionDiffComparison(
                        old_finding_id=old_f.finding_id,
                        identity=ident,
                        status=VersionDiffStatus.RESOLVED,
                        reason=(
                            f"修改后提供了新的{'; '.join(ev_cats) or '证据'},"
                            f"该问题不再触发。"
                        ),
                        old_level=old_f.level.value,
                    ))
            else:
                # 身份匹配:仍存在或缓解
                new_f = matches[0]
                matched_new_ids.add(new_f.finding_id)
                old_sev = _SEVERITY_ORDER[old_f.level]
                new_sev = _SEVERITY_ORDER[new_f.level]

                if new_sev < old_sev:
                    comparisons.append(VersionDiffComparison(
                        old_finding_id=old_f.finding_id,
                        identity=ident,
                        status=VersionDiffStatus.MITIGATED,
                        reason=(
                            f"问题仍然存在,但严重度从{old_f.level.value}"
                            f"降为{new_f.level.value}。"
                        ),
                        old_level=old_f.level.value,
                        new_level=new_f.level.value,
                        new_finding_id=new_f.finding_id,
                    ))
                else:
                    comparisons.append(VersionDiffComparison(
                        old_finding_id=old_f.finding_id,
                        identity=ident,
                        status=VersionDiffStatus.PERSISTS,
                        reason=(
                            f"修改后该问题仍然存在(严重度:{new_f.level.value})。"
                            if new_sev == old_sev
                            else f"问题未解决,严重度反而从{old_f.level.value}升为{new_f.level.value}。"
                        ),
                        old_level=old_f.level.value,
                        new_level=new_f.level.value,
                        new_finding_id=new_f.finding_id,
                    ))

        # 新问题:新报告中有、旧报告中无此身份
        new_issue_ids: list[str] = []
        old_identities = {
            self.compute_identity(f).identity_hash for f in old_report.findings
        }
        for new_f in new_report.findings:
            if new_f.finding_id in matched_new_ids:
                continue
            ident = self.compute_identity(new_f)
            if ident.identity_hash in old_identities:
                continue
            comp = VersionDiffComparison(
                identity=ident,
                status=VersionDiffStatus.NEW_ISSUE,
                reason=f"新发现的问题:{new_f.title}",
                new_level=new_f.level.value,
                new_finding_id=new_f.finding_id,
            )
            comparisons.append(comp)
            new_issue_ids.append(comp.comparison_id)

        # 修改理由对照
        alignment = self._align_revision(
            revision_note, old_report, store
        )

        return VersionDiffResult(
            session_id=session_id,
            old_report_id=old_report.report_id,
            new_report_id=new_report.report_id,
            comparisons=comparisons,
            new_issue_ids=new_issue_ids,
            revision_alignment=alignment,
            created_at=datetime.now().isoformat(),
        )

    # ---- 修改理由对照 ----

    def _align_revision(
        self,
        revision_note: str,
        old_report: ReviewReport,
        store,
    ) -> RevisionAlignment:
        """将学生修改理由与事实层面实际变化对照。"""
        if not revision_note:
            return RevisionAlignment(
                alignment=RevisionAlignmentLevel.NOT_ALIGNED,
                alignment_detail="学生未提交修改理由。",
            )

        # 1. 从修改理由提取声称改动(关键词 → 类别)
        claimed_changes: list[str] = []
        claimed_cats: set[str] = set()
        note_lower = revision_note.lower()
        for kw, cat in _CLAIM_KEYWORDS:
            if kw in note_lower and cat not in claimed_cats:
                claimed_cats.add(cat)
                claimed_changes.append(f"声称修改了{cat}(关键词:{kw})")

        # 2. 事实层面实际变化:旧报告证据值 vs 当前事实值
        actual_changes: list[FactChange] = []
        changed_cats: set[str] = set()
        old_by_cat: dict[str, list[str]] = {}
        for f in old_report.findings:
            for ref in f.evidence:
                old_by_cat.setdefault(ref.category.value, []).append(ref.value)

        current_by_cat: dict[str, list[str]] = {}
        for fact in store.facts.values():
            if fact.is_usable():
                current_by_cat.setdefault(fact.category.value, []).append(
                    fact.effective_value()
                )

        all_cats = set(old_by_cat.keys()) | set(current_by_cat.keys())
        for cat in sorted(all_cats):
            old_vals = old_by_cat.get(cat, [])
            new_vals = current_by_cat.get(cat, [])
            if not old_vals and new_vals:
                actual_changes.append(FactChange(
                    category=cat, new_value="; ".join(new_vals[:3]),
                    change_type="added",
                ))
                changed_cats.add(cat)
            elif old_vals and not new_vals:
                actual_changes.append(FactChange(
                    category=cat, old_value="; ".join(old_vals[:3]),
                    change_type="removed",
                ))
                changed_cats.add(cat)
            elif old_vals and new_vals and set(old_vals) != set(new_vals):
                actual_changes.append(FactChange(
                    category=cat,
                    old_value="; ".join(old_vals[:3]),
                    new_value="; ".join(new_vals[:3]),
                    change_type="modified",
                ))
                changed_cats.add(cat)

        # 3. 对照
        if not claimed_cats:
            alignment = RevisionAlignmentLevel.PARTIALLY_ALIGNED
            detail = "修改理由中未识别到明确的改动声明(如划分方式/基线/指标等)。"
        elif claimed_cats and claimed_cats.issubset(changed_cats):
            alignment = RevisionAlignmentLevel.ALIGNED
            detail = (
                f"声称改动({'; '.join(sorted(claimed_cats))})与事实层面实际变化"
                f"({'; '.join(sorted(changed_cats))})一致。"
            )
        elif claimed_cats & changed_cats:
            alignment = RevisionAlignmentLevel.PARTIALLY_ALIGNED
            matched = claimed_cats & changed_cats
            unmatched = claimed_cats - changed_cats
            detail = (
                f"部分一致:声称改动中{'; '.join(sorted(matched))}确有事实变化,"
                f"但{'; '.join(sorted(unmatched))}在事实层面未见变化。"
            )
        else:
            alignment = RevisionAlignmentLevel.NOT_ALIGNED
            detail = (
                f"不一致:声称改动({'; '.join(sorted(claimed_cats))})"
                f"在事实层面均未发生变化(实际变化:{'; '.join(sorted(changed_cats)) or '无'})。"
                f"请确认是否真正修改了实验,还是仅修改了描述。"
            )

        return RevisionAlignment(
            revision_note=revision_note,
            claimed_changes=claimed_changes,
            actual_changes=actual_changes,
            alignment=alignment,
            alignment_detail=detail,
        )

    # ---- 复审入口 ----

    def run_version_diff(
        self, session_id: str, revision_note: str = ""
    ) -> VersionDiffResult:
        """版本差异复审:重新审查 → 与上一份报告对比(稳定身份+五态)。"""
        store = data_store.require(session_id)
        old_report = store.latest_report()
        if old_report is None:
            raise ValueError("尚无历史报告,请先完成一次审查再复审。")

        new_report = review_service.run_review(session_id)
        result = self.compute_diff(
            session_id, old_report, new_report, revision_note
        )
        store.version_diffs.append(result)
        data_store.persist(session_id)
        logger.info(
            "版本差异复审完成:resolved=%d mitigated=%d persists=%d new=%d insufficient=%d",
            sum(1 for c in result.comparisons if c.status == VersionDiffStatus.RESOLVED),
            sum(1 for c in result.comparisons if c.status == VersionDiffStatus.MITIGATED),
            sum(1 for c in result.comparisons if c.status == VersionDiffStatus.PERSISTS),
            sum(1 for c in result.comparisons if c.status == VersionDiffStatus.NEW_ISSUE),
            sum(1 for c in result.comparisons if c.status == VersionDiffStatus.INSUFFICIENT_EVIDENCE),
        )
        return result

    def get_latest_diff(self, session_id: str) -> VersionDiffResult | None:
        store = data_store.get(session_id)
        if not store or not store.version_diffs:
            return None
        return store.version_diffs[-1]

    # ---- 人工复核标签 ----

    def add_manual_label(
        self,
        session_id: str,
        comparison_id: str,
        actual_status: str,
        labeled_by: str = "",
        note: str = "",
    ) -> ManualReviewLabel:
        """添加人工复核标签(验证已解决精确率)。"""
        store = data_store.require(session_id)
        try:
            status = VersionDiffStatus(actual_status)
        except ValueError as exc:
            raise ValueError(f"无效状态:{actual_status}") from exc

        label = ManualReviewLabel(
            comparison_id=comparison_id,
            actual_status=status,
            labeled_by=labeled_by or "human",
            labeled_at=datetime.now().isoformat(),
            note=note,
        )
        store.manual_labels.append(label)
        data_store.persist(session_id)
        return label

    # ---- 统计(验证指标) ----

    def get_stats(self, session_id: str) -> VersionDiffStats:
        """单会话统计:五态计数 + 已解决精确率(人工标签)+ 迁移表现。"""
        store = data_store.get(session_id)
        if not store:
            return VersionDiffStats()

        all_comparisons: list[VersionDiffComparison] = []
        for diff in store.version_diffs:
            all_comparisons.extend(diff.comparisons)

        resolved = [c for c in all_comparisons if c.status == VersionDiffStatus.RESOLVED]
        mitigated = [c for c in all_comparisons if c.status == VersionDiffStatus.MITIGATED]
        persists = [c for c in all_comparisons if c.status == VersionDiffStatus.PERSISTS]
        new_issues = [c for c in all_comparisons if c.status == VersionDiffStatus.NEW_ISSUE]
        insufficient = [c for c in all_comparisons if c.status == VersionDiffStatus.INSUFFICIENT_EVIDENCE]

        # 已解决精确率:人工标签中,系统判 resolved 且人工也判 resolved 的比例
        labels_by_comp = {l.comparison_id: l for l in store.manual_labels}
        resolved_labeled = [
            labels_by_comp[c.comparison_id]
            for c in resolved
            if c.comparison_id in labels_by_comp
        ]
        resolved_correct = sum(
            1 for l in resolved_labeled if l.actual_status == VersionDiffStatus.RESOLVED
        )
        resolved_precision = (
            resolved_correct / len(resolved_labeled) if resolved_labeled else 0.0
        )

        # 迁移表现
        answers = store.migration_answers
        migration_total = len(answers)
        migration_avg = (
            sum(a.total_score for a in answers) / migration_total
            if migration_total else 0.0
        )
        migration_pass = (
            sum(1 for a in answers if a.total_score >= 0.6) / migration_total
            if migration_total else 0.0
        )

        # 修改理由一致率
        aligned_count = sum(
            1 for d in store.version_diffs
            if d.revision_alignment.alignment == RevisionAlignmentLevel.ALIGNED
        )
        revision_aligned_rate = (
            aligned_count / len(store.version_diffs) if store.version_diffs else 0.0
        )

        return VersionDiffStats(
            total_comparisons=len(all_comparisons),
            resolved_count=len(resolved),
            mitigated_count=len(mitigated),
            persists_count=len(persists),
            new_issue_count=len(new_issues),
            insufficient_evidence_count=len(insufficient),
            manual_labels=len(resolved_labeled),
            resolved_precision=resolved_precision,
            migration_total=migration_total,
            migration_avg_score=migration_avg,
            migration_pass_rate=migration_pass,
            revision_aligned_rate=revision_aligned_rate,
        )


version_diff_service = VersionDiffService()