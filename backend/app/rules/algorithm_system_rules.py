"""算法与系统性能实验的审查规则。

每条规则检查一类"主张-实验-证据"对应关系,输出三级发现:
- 明确矛盾:计划与执行或主张与证据直接冲突;
- 潜在风险:迹象可疑但缺完整上下文;
- 信息不足:无法核实,需补材料。

所有发现的 evidence 均引用具体事实,可回溯原文。
"""

from __future__ import annotations

import re

from app.models.claim import ExperimentType
from app.models.evidence import (
    EvidenceRef,
    ExtractedFact,
    FactCategory,
    MaterialRole,
    ParsedDocument,
)
from app.models.review import Finding, FindingLevel
from app.rules.base import RuleBase


def _to_ref(f: ExtractedFact) -> EvidenceRef:
    """事实 -> 证据引用(携带原文片段,前端可直接展示)。"""
    return EvidenceRef(
        fact_id=f.fact_id, category=f.category, value=f.effective_value(), source=f.source
    )


def _refs(facts: list[ExtractedFact]) -> list[EvidenceRef]:
    return [_to_ref(f) for f in facts]


def _match_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


# 比较信号
_COMPARE_PATTERNS = [
    r"比\s*\S+", r"优于", r"超过", r"好于", r"强于", r"快于",
    r"outperform", r"better\s+than", r"superior",
]
# 稳定性信号
_STABILITY_PATTERNS = [r"更?稳定", r"鲁棒", r"robust", r"stable", r"consistent"]
# 多次运行信号
_MULTI_RUN_PATTERNS = [
    r"mean\s*[±+/-]\s*std", r"均值\s*[±]\s*标准差", r"±\s*[\d.]+",
    r"n[_-]?runs", r"n_repeats", r"重复.{0,6}\d+\s*次",
]
# 性能/速度信号
_PERF_PATTERNS = [
    r"延迟", r"吞吐", r"latency", r"throughput", r"QPS",
    r"响应时间", r"运行时间", r"runtime", r"加速比", r"speedup",
]


class BaselineCheckRule(RuleBase):
    """规则:主张含比较关系时,基线方法是否明确且实际执行。"""

    rule_id = "as_baseline_check"
    title = "基线对比完整性"
    experiment_type = ExperimentType.ALGORITHM_SYSTEM

    def check(self, facts, docs, claim_texts, claim_ids):
        has_compare = any(_match_any(t, _COMPARE_PATTERNS) for t in claim_texts)
        if not has_compare:
            return []

        grouped = self.group_by_category(facts)
        baseline_facts = grouped.get(FactCategory.BASELINE, [])

        if not baseline_facts:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.INSUFFICIENT,
                    title="主张涉及算法/系统对比,但未提供基线方法信息",
                    claim_ids=claim_ids,
                    evidence=[],
                    missing_evidence=["基线方法名称及配置", "基线在同一环境下的运行结果"],
                    suggestion="补充基线方法的名称、版本与配置,并在相同环境下运行对比。",
                    suggestion_type="clarify",
                    reasoning="对比类主张需要明确的基线方法与可核对的运行结果。",
                )
            ]

        exec_baselines = [
            f for f in baseline_facts
            if docs[f.source.material_id].role == MaterialRole.EXECUTION
        ]
        if not exec_baselines:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.RISK,
                    title="基线方法仅在计划中提及,执行材料中未找到实际运行记录",
                    claim_ids=claim_ids,
                    evidence=_refs(baseline_facts),
                    missing_evidence=["基线方法的实际运行代码或结果"],
                    suggestion="确认基线是否在相同环境下实际运行;若未运行,补充运行记录或收窄对比结论。",
                    suggestion_type="clarify",
                    reasoning="基线只出现在计划中,无法确认是否真的执行了对比实验。",
                )
            ]
        return []


class MetricCheckRule(RuleBase):
    """规则:性能主张是否有指标数据支撑。"""

    rule_id = "as_metric_check"
    title = "性能指标支撑"
    experiment_type = ExperimentType.ALGORITHM_SYSTEM

    def check(self, facts, docs, claim_texts, claim_ids):
        has_perf_claim = any(
            _match_any(t, _COMPARE_PATTERNS + _PERF_PATTERNS) for t in claim_texts
        )
        if not has_perf_claim:
            return []

        grouped = self.group_by_category(facts)
        metric_facts = grouped.get(FactCategory.METRIC, [])

        if not metric_facts:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.INSUFFICIENT,
                    title="主张涉及性能比较,但未提供任何评价指标数据",
                    claim_ids=claim_ids,
                    evidence=[],
                    missing_evidence=["评价指标的定义与具体数值", "基线与提出方法在同一指标上的对比结果"],
                    suggestion="补充评价指标(如延迟、吞吐、准确率等)的具体数值结果。",
                    suggestion_type="clarify",
                    reasoning="性能比较主张需要指标数值作为证据。",
                )
            ]

        exec_metrics = [
            f for f in metric_facts
            if docs[f.source.material_id].role == MaterialRole.EXECUTION
        ]
        if not exec_metrics:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.RISK,
                    title="指标仅在计划中声明,执行材料中未找到实际测量结果",
                    claim_ids=claim_ids,
                    evidence=_refs(metric_facts),
                    missing_evidence=["实际运行产出的指标数值"],
                    suggestion="补充实验运行产出的指标结果(如日志、输出文件)。",
                    suggestion_type="clarify",
                    reasoning="计划中声明指标不等于实际测量了指标,需要执行侧证据。",
                )
            ]
        return []


class StabilityRepetitionRule(RuleBase):
    """规则:稳定性/鲁棒性主张是否有多次运行证据。"""

    rule_id = "as_stability_repetition"
    title = "稳定性主张与重复运行"
    experiment_type = ExperimentType.ALGORITHM_SYSTEM

    def check(self, facts, docs, claim_texts, claim_ids):
        stability_claims = [
            (cid, t)
            for cid, t in zip(claim_ids, claim_texts)
            if _match_any(t, _STABILITY_PATTERNS)
        ]
        if not stability_claims:
            return []

        target_ids = [cid for cid, _ in stability_claims]
        grouped = self.group_by_category(facts)
        rep_facts = grouped.get(FactCategory.REPETITION, [])

        has_multi_run = any(
            _match_any(f.effective_value(), _MULTI_RUN_PATTERNS) for f in rep_facts
        )
        if has_multi_run:
            return []

        has_seed_only = any(
            re.search(r"random_state|seed|manual_seed", f.effective_value(), re.IGNORECASE)
            for f in rep_facts
        )
        if has_seed_only:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.RISK,
                    title="主张涉及稳定性,但只找到单次运行的随机种子,无多次运行证据",
                    claim_ids=target_ids,
                    evidence=_refs(rep_facts),
                    missing_evidence=["多次运行的均值±标准差结果"],
                    suggestion="补充多次重复运行的均值±标准差,否则将稳定性主张收窄为单次运行表现。",
                    suggestion_type="narrow",
                    reasoning="稳定性/鲁棒性结论需要多次运行的统计证据支撑,单次运行无法证明稳定性。",
                )
            ]

        return [
            Finding(
                rule_id=self.rule_id,
                level=FindingLevel.INSUFFICIENT,
                title="主张涉及稳定性,但未提供任何重复运行证据",
                claim_ids=target_ids,
                evidence=[],
                missing_evidence=["重复运行次数与均值±标准差结果"],
                suggestion="补充重复运行实验(建议≥5次)并报告均值±标准差,或收窄主张。",
                suggestion_type="clarify",
                reasoning="稳定性主张需要多次运行的统计证据。",
            )
        ]


class PlanExecutionCoverageRule(RuleBase):
    """规则:算法/系统实验是否同时提供了计划与执行材料。"""

    rule_id = "as_plan_exec_coverage"
    title = "计划与执行材料完整性"
    experiment_type = ExperimentType.ALGORITHM_SYSTEM

    def check(self, facts, docs, claim_texts, claim_ids):
        has_plan, has_exec = self.has_plan_and_execution(docs)
        if has_plan and has_exec:
            return []

        missing = []
        if not has_plan:
            missing.append("实验计划/设计方案")
        if not has_exec:
            missing.append("实际执行(代码、配置或运行结果)")
        return [
            Finding(
                rule_id=self.rule_id,
                level=FindingLevel.INSUFFICIENT,
                title="缺少计划或执行材料,无法进行对照审查",
                claim_ids=claim_ids,
                evidence=[],
                missing_evidence=missing,
                suggestion="同时上传实验计划与实际执行材料,系统才能核对两者是否一致。",
                suggestion_type="clarify",
                reasoning="研证的核心是主张、计划与执行三者对照,缺少任一侧都无法完成审查。",
            )
        ]