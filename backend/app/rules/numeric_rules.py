"""Surface bounded arithmetic contradictions in the main report, not only the graph."""
from app.models.evidence import EvidenceRef
from app.models.review import Finding, FindingLevel
from app.rules.base import RuleBase
from app.services.numeric_evidence import evaluate_fact


class NumericComparisonRule(RuleBase):
    rule_id = "numeric_comparison"
    title = "限定条件内的数值比较"
    aspect = "comparison"

    def check(self, facts, docs, claim_texts, claim_ids):
        findings = []
        for text, cid in zip(claim_texts, claim_ids):
            results = [(f, result) for f in facts if (result := evaluate_fact(f, docs, self.aspect, text)) is not None]
            relations = {result[0] for _, result in results}
            if not relations or relations == {"supports"}:
                continue
            conflict = "unknown" in relations or len(relations) > 1
            findings.append(Finding(rule_id=self.rule_id, claim_ids=[cid], issue_scope=self.aspect,
                level=FindingLevel.INSUFFICIENT if conflict else FindingLevel.CONTRADICTION,
                title="结果记录相互冲突，需澄清适用测试" if conflict else "提供的数值不支持该限定比较主张",
                evidence=[EvidenceRef(fact_id=f.fact_id, category=f.category,
                    value=f.effective_value(), source=f.source) for f, _ in results],
                missing_evidence=["对应主张的唯一测试范围与一致结果"] if conflict else [],
                suggestion="核对原始记录、指标方向与方法名称；如数值无误，应修改这条主张，或补充新的实际结果。",
                suggestion_type="clarify" if conflict else "narrow",
                reasoning="\n".join(result[1] for _, result in results)))
        return findings


class NumericStabilityRule(NumericComparisonRule):
    rule_id = "numeric_stability"
    title = "有限运行样本的波动比较"
    aspect = "stability"
