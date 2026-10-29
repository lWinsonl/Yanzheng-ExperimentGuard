"""复查服务:比较前后版本,显示哪些疑点已解除、哪些仍待核实。

流程:学生提交修改理由与新材料 -> 重新提取/确认 -> 重新审查 ->
对比新旧报告:同一 rule_id 的发现是否仍触发。
"""

from __future__ import annotations

from app.models.review import (
    Finding,
    FindingLevel,
    RecheckComparison,
    RecheckResult,
    ReviewReport,
)
from app.services.review import review_service
from app.services.store import data_store


class RecheckService:
    """复查服务。"""

    def run_recheck(self, session_id: str, revision_note: str = "") -> RecheckResult:
        """基于当前(已补充材料并确认事实的)状态重新审查,并与上一份报告对比。"""
        store = data_store.require(session_id)
        old_report = store.latest_report()
        if old_report is None:
            raise ValueError("尚无历史报告,请先完成一次审查再复查。")

        new_report = review_service.run_review(session_id)
        comparisons = self._compare(old_report, new_report)

        old_ids = {f.rule_id for f in old_report.findings}
        new_ids = {f.rule_id for f in new_report.findings}
        newly_raised = [
            f.finding_id for f in new_report.findings if f.rule_id not in old_ids
        ]

        result = RecheckResult(
            session_id=session_id,
            old_report_id=old_report.report_id,
            new_report_id=new_report.report_id,
            comparisons=comparisons,
            newly_raised=newly_raised,
            revision_note=revision_note,
        )
        store.add_recheck(result)
        data_store.persist(session_id)
        return result

    def _compare(
        self, old: ReviewReport, new: ReviewReport
    ) -> list[RecheckComparison]:
        """按 rule_id 对比:旧发现是否在新报告中仍触发。"""
        new_by_rule: dict[str, list[Finding]] = {}
        for f in new.findings:
            new_by_rule.setdefault(f.rule_id, []).append(f)

        comparisons: list[RecheckComparison] = []
        for old_f in old.findings:
            still = new_by_rule.get(old_f.rule_id, [])
            if not still:
                comparisons.append(
                    RecheckComparison(
                        finding_id=old_f.finding_id,
                        rule_id=old_f.rule_id,
                        title=old_f.title,
                        resolved=True,
                        note="修改后该疑点不再触发。",
                    )
                )
            else:
                # 仍触发:若严重度降低(矛盾->风险->不足)也标注
                severity = {
                    FindingLevel.CONTRADICTION: 2,
                    FindingLevel.RISK: 1,
                    FindingLevel.INSUFFICIENT: 0,
                }
                new_level = min((f.level for f in still), key=lambda lv: severity[lv])
                level_hint = ""
                if new_level != old_f.level:
                    level_hint = f"严重度由 {old_f.level.value} 降为 {new_level.value}。"
                comparisons.append(
                    RecheckComparison(
                        finding_id=old_f.finding_id,
                        rule_id=old_f.rule_id,
                        title=old_f.title,
                        resolved=False,
                        new_finding_id=still[0].finding_id,
                        note=f"仍待核实。{level_hint}".strip(),
                    )
                )
        return comparisons


recheck_service = RecheckService()