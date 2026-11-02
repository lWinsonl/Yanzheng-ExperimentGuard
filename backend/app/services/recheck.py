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
        from app.services.version_diff import version_diff_service
        from app.models.version_diff import VersionDiffStatus
        store = data_store.require(session_id)
        diff = version_diff_service.run_version_diff(session_id, revision_note)
        old = store.reports[diff.old_report_id]
        by_id = {f.finding_id: f for f in old.findings}
        comparisons = [RecheckComparison(finding_id=c.old_finding_id,
            rule_id=by_id[c.old_finding_id].rule_id, title=by_id[c.old_finding_id].title,
            resolved=c.status == VersionDiffStatus.RESOLVED,
            new_finding_id=c.new_finding_id or None, note=c.reason)
            for c in diff.comparisons if c.old_finding_id in by_id]
        result = RecheckResult(session_id=session_id, old_report_id=diff.old_report_id,
            new_report_id=diff.new_report_id, comparisons=comparisons,
            newly_raised=[c.new_finding_id for c in diff.comparisons if c.status == VersionDiffStatus.NEW_ISSUE],
            revision_note=revision_note)
        store.add_recheck(result)
        data_store.persist(session_id)
        return result



recheck_service = RecheckService()
