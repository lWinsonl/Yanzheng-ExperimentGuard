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
            issue_scope=finding.issue_scope,
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
        def key(f):
            return (f.rule_id, tuple(sorted(f.claim_ids)), f.issue_scope)

        old_groups, new_groups = {}, {}
        for f in old_report.findings:
            old_groups.setdefault(key(f), []).append(f)
        for f in new_report.findings:
            new_groups.setdefault(key(f), []).append(f)
        comparisons, matched_new_ids = [], set()
        for old_f in old_report.findings:
            ident = self.compute_identity(old_f)
            matches = new_groups.get(key(old_f), [])
            status, reason, new_f = VersionDiffStatus.INSUFFICIENT_EVIDENCE, "", None
            if len(old_groups[key(old_f)]) > 1 or len(matches) > 1:
                matched_new_ids.update(f.finding_id for f in matches)
                reason = "同规则、主张与作用范围中有多个条目，无法唯一配对；未将任何旧项自动判为已解决。"
            elif matches:
                new_f = matches[0]
                matched_new_ids.add(new_f.finding_id)
                if new_f.level == FindingLevel.INSUFFICIENT and old_f.level != FindingLevel.INSUFFICIENT:
                    reason = "当前仍缺证据，无法把严重度降低解释为问题已缓解。" + new_f.title
                elif _SEVERITY_ORDER[new_f.level] < _SEVERITY_ORDER[old_f.level]:
                    status = VersionDiffStatus.MITIGATED
                    reason = "这项问题仍需处理，但相关风险已缓解：" + new_f.title
                else:
                    status = VersionDiffStatus.PERSISTS
                    reason = "这项问题仍存在：" + new_f.title + "。补充材料不等于问题已解决。"
            else:
                status, reason = self._resolution_status(old_f, old_report, new_report)
            comparisons.append(VersionDiffComparison(
                old_finding_id=old_f.finding_id, identity=ident, status=status, reason=reason,
                old_level=old_f.level.value, new_level=new_f.level.value if new_f else "",
                new_finding_id=new_f.finding_id if new_f else ""))

        new_issue_ids = []
        for new_f in new_report.findings:
            if new_f.finding_id in matched_new_ids:
                continue
            comp = VersionDiffComparison(identity=self.compute_identity(new_f),
                status=VersionDiffStatus.NEW_ISSUE, reason="新发现的问题：" + new_f.title,
                new_level=new_f.level.value, new_finding_id=new_f.finding_id)
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

    @staticmethod
    def _snapshot_values(report):
        values = {}
        material = {d["material_id"]: d for d in report.material_snapshot}
        for fact in report.fact_snapshot:
            doc = material.get(fact.source.material_id, {})
            value = fact.effective_value()
            try:
                import json
                value = json.dumps(json.loads(value), ensure_ascii=False, sort_keys=True)
            except (ValueError, TypeError):
                value = " ".join(value.split())
            provenance = "/".join(str(doc.get(k, "unknown")) for k in ("role", "origin", "kind"))
            values.setdefault(fact.category.value, set()).add(f"[{provenance}] {value}")
        values["claim_scope"] = {f"{cid}: {text}" for cid, text in report.claim_snapshot.items()}
        return values

    def _resolution_status(self, finding, old, new):
        unknown = VersionDiffStatus.INSUFFICIENT_EVIDENCE
        if not old.snapshot_version or not new.snapshot_version:
            return unknown, "旧版报告缺少完整事实快照，无法确认问题已解决。请以当前报告建立新基准。"
        if finding.rule_id not in new.checked_rule_ids or finding.rule_id in new.failed_rule_ids:
            return unknown, "对应规则未完成本次审查，不能将未触发解释为已解决。"
        if any(old.claim_snapshot.get(cid) != new.claim_snapshot.get(cid) for cid in finding.claim_ids):
            return unknown, "相关主张已修改或移除，需要核对新的范围；不能自动视为原实验问题已修复。"
        if finding.issue_scope and finding.issue_scope not in ("comparison", "stability"):
            return unknown, "缺少该作用范围的独立通过记录，无法用其他数据集或比较对象的变化解除此项。"
        required = {ref.category.value for ref in finding.evidence}
        if not required:
            required = {"data_split"} if "split" in finding.rule_id or "generalization" in finding.rule_id else (
                {"baseline"} if "baseline" in finding.rule_id else {"repetition"} if "repetition" in finding.rule_id else {"metric"})
        before, after = self._snapshot_values(old), self._snapshot_values(new)
        if not any(after.get(cat) and after.get(cat) != before.get(cat) for cat in required):
            return unknown, "原发现已不再出现，但没有核对到相关已确认事实的实际变化；删除、拒绝或待确认材料不构成修复。"
        return VersionDiffStatus.RESOLVED, "相关已确认事实发生变化，且对应规则已完成并不再触发；仅表示此规则下的问题解除，不为整个实验背书。"

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

        # 使用完整、不可变的报告快照；不能用“报告恰好引用了什么”还原旧事实。
        if not old_report.snapshot_version:
            return RevisionAlignment(revision_note=revision_note, claimed_changes=claimed_changes,
                alignment=RevisionAlignmentLevel.UNKNOWN,
                alignment_detail="旧报告没有完整事实快照，无法核对所声称的修改；请先建立新基准。")
        from app.models.review import ReviewReport
        current = ReviewReport(session_id=store.session.session_id, snapshot_version=1,
            fact_snapshot=[f.model_copy(deep=True) for f in store.usable_facts()],
            claim_snapshot={c.claim_id: c.text for c in store.session.claims},
            material_snapshot=[{"material_id": d.material_id, "role": d.role.value,
                "kind": d.kind.value, "origin": d.origin} for d in store.docs.values()])
        old_by_cat = self._snapshot_values(old_report)
        current_by_cat = self._snapshot_values(current)
        actual_changes, changed_cats = [], set()

        all_cats = set(old_by_cat.keys()) | set(current_by_cat.keys())
        for cat in sorted(all_cats):
            old_vals = sorted(old_by_cat.get(cat, set()))
            new_vals = sorted(current_by_cat.get(cat, set()))
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
                f"({'; '.join(sorted(changed_cats))})有对应变化；仅核对类别，不证明修改方向正确或问题已解决。"
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
                "这里只核对已确认事实；请补充对应代码或记录，不能据此断言完整实验没有修改。"
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
        old_report = store.reports.get(store.baseline_report_id) or store.latest_report()
        if old_report is None:
            raise ValueError("尚无历史报告,请先完成一次审查再复审。")

        new_report = review_service.run_review(session_id)
        result = self.compute_diff(
            session_id, old_report, new_report, revision_note
        )
        store.version_diffs.append(result)
        store.baseline_report_id = new_report.report_id
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
        answers = [a for a in store.migration_answers
                   if a.score_status == "model_feedback" and a.total_score is not None]
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
