from app.models.evidence import EvidenceRef
from app.models.review import Finding, FindingLevel
from app.rules.base import RuleBase
from app.services.program_checks import build_checks


class RecallDenominatorRule(RuleBase):
    rule_id = "binary_recall_denominator"
    title = "二分类召回率分母核对"

    def check(self, facts, docs, claim_texts, claim_ids):
        by_id = {f.fact_id: f for f in facts}
        findings = []
        for check in build_checks(facts, docs, claim_texts):
            if check.kind != "recall_defined" or check.status != "failed":
                continue
            findings.append(Finding(rule_id=self.rule_id, level=FindingLevel.CONTRADICTION,
                title="所提供表格没有实际正类，无法据此估计召回率",
                claim_ids=[cid for text, cid in zip(claim_texts, claim_ids) if "recall" in text.lower() or "召回率" in text],
                issue_scope=check.scope_key, reasoning=check.basis,
                evidence=[EvidenceRef(fact_id=fid, category=by_id[fid].category,
                    value=by_id[fid].effective_value(), source=by_id[fid].source) for fid in check.fact_ids],
                suggestion="核对任务正类与评分窗口；将该表召回率标为不可估计，或提供含实际正类、符合原任务的新评估记录。",
                suggestion_type="narrow"))
        return findings
