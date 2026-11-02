"""审查服务:运行学科规则 -> 生成报告。

只使用用户已确认/纠正的事实;未确认的事实计入 skipped,
并在报告中显式提示,避免"悄悄用猜测下结论"。
"""

from __future__ import annotations

from datetime import datetime

from app.models.review import ReviewReport
from app.rules import get_rules_for
from app.services.store import data_store
from app.services.program_checks import build_checks


class ReviewService:
    """审查服务。"""

    def run_review(self, session_id: str) -> ReviewReport:
        store = data_store.require(session_id)
        session = store.session

        usable = store.usable_facts()
        skipped = len(store.facts) - len(usable)

        claim_texts = [c.text for c in session.claims]
        claim_ids = [c.claim_id for c in session.claims]

        rules = get_rules_for(session.experiment_type)
        findings: list = []
        checked, failed = [], []
        for rule in rules:
            try:
                findings.extend(rule.check(usable, store.docs, claim_texts, claim_ids))
                checked.append(rule.rule_id)
            except Exception as exc:  # noqa: BLE001
                failed.append(rule.rule_id)
                # 单条规则异常不阻断整体审查,但需记录
                from app.models.review import Finding, FindingLevel

                findings.append(
                    Finding(
                        rule_id=rule.rule_id,
                        level=FindingLevel.INSUFFICIENT,
                        title=f"规则 {rule.rule_id} 执行异常,该维度未完成审查",
                        claim_ids=claim_ids,
                        evidence=[],
                        missing_evidence=[f"规则 {rule.rule_id} 的完整执行"],
                        suggestion="请检查材料格式后重新审查,或联系维护者。",
                        suggestion_type="clarify",
                        reasoning=f"异常信息:{exc}",
                    )
                )

        report = ReviewReport(
            session_id=session_id,
            findings=findings,
            usable_fact_count=len(usable),
            skipped_fact_count=skipped,
            created_at=datetime.now().isoformat(),
            snapshot_version=1,
            checked_rule_ids=checked,
            failed_rule_ids=failed,
            program_checks=build_checks(usable, store.docs, claim_texts),
            fact_snapshot=[f.model_copy(deep=True) for f in usable],
            claim_snapshot={c.claim_id: c.text for c in session.claims},
            material_snapshot=[{"material_id": d.material_id, "role": d.role.value,
                                "kind": d.kind.value, "origin": d.origin}
                               for d in store.docs.values()],
        )
        store.add_report(report)
        if not store.baseline_report_id:
            store.baseline_report_id = report.report_id
        data_store.persist(session_id)
        return report

    def get_report(self, session_id: str, report_id: str) -> ReviewReport | None:
        store = data_store.get(session_id)
        if store is None:
            return None
        return store.reports.get(report_id)

    def latest_report(self, session_id: str) -> ReviewReport | None:
        store = data_store.get(session_id)
        if store is None:
            return None
        return store.latest_report()


review_service = ReviewService()
