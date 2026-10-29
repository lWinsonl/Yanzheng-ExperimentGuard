"""数据与模型实验的审查规则。

每条规则检查一类"主张-实验-证据"对应关系,输出三级发现:
- 明确矛盾:计划与执行或主张与证据直接冲突;
- 潜在风险:迹象可疑但缺完整上下文;
- 信息不足:无法核实,需补材料。

所有发现的 evidence 均引用具体事实,可回溯原文。
"""

from __future__ import annotations

import re

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


# 数据划分信号
_GROUP_SPLIT_PATTERNS = [
    r"按\s*(设备|机器|机组|单元|组|用户|病人|被试)",
    r"GroupShuffleSplit",
    r"GroupKFold",
    r"group\s*=",
]
_RECORD_SPLIT_PATTERNS = [
    r"train_test_split",
    r"(随机|按记录|按样本|按条)",
    r"shuffle\s*=\s*True",
]
# 主张范围信号
_NEW_ENTITY_PATTERNS = [r"新\s*(设备|机器|用户|病人|场景|领域)", r"未见", r"unseen", r"new\s+(device|machine|user)"]
# 稳定性信号
_STABILITY_PATTERNS = [r"更?稳定", r"鲁棒", r"robust", r"stable", r"consistent"]
# 多次运行信号
_MULTI_RUN_PATTERNS = [r"mean\s*[±+/-]\s*std", r"均值\s*[±]\s*标准差", r"±\s*[\d.]+", r"n[_-]?runs", r"n_repeats", r"重复.{0,6}\d+\s*次"]
# 比较信号
_COMPARE_PATTERNS = [r"比\s*\S+", r"优于", r"超过", r"好于", r"强于", r"outperform", r"better\s+than", r"superior"]


class SplitConsistencyRule(RuleBase):
    """规则:计划与执行的数据划分方式是否一致。"""

    rule_id = "dm_split_consistency"
    title = "数据划分一致性"

    def check(self, facts, docs, claim_texts, claim_ids):
        grouped = self.group_by_category(facts)
        split_facts = grouped.get(FactCategory.DATA_SPLIT, [])
        if not split_facts:
            return []

        plan_facts = [f for f in split_facts if docs[f.source.material_id].role == MaterialRole.PLAN]
        exec_facts = [f for f in split_facts if docs[f.source.material_id].role == MaterialRole.EXECUTION]

        if not plan_facts or not exec_facts:
            # 只有一侧有划分信息,无法对比
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.INSUFFICIENT,
                    title="缺少计划或执行一侧的数据划分信息,无法核对一致性",
                    claim_ids=claim_ids,
                    evidence=_refs(plan_facts or exec_facts),
                    missing_evidence=["实验计划中的数据划分说明", "或代码/配置中的划分实现"],
                    suggestion="补充实验计划或执行代码中的数据划分说明,以便核对两者是否一致。",
                    suggestion_type="clarify",
                    reasoning="数据划分的一致性需要计划与执行两侧均有记录才能核对。",
                )
            ]

        plan_group = any(_match_any(f.effective_value(), _GROUP_SPLIT_PATTERNS) for f in plan_facts)
        plan_record = any(_match_any(f.effective_value(), _RECORD_SPLIT_PATTERNS) for f in plan_facts)
        exec_group = any(_match_any(f.effective_value(), _GROUP_SPLIT_PATTERNS) for f in exec_facts)
        exec_record = any(_match_any(f.effective_value(), _RECORD_SPLIT_PATTERNS) for f in exec_facts)

        if plan_group and exec_record and not exec_group:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.CONTRADICTION,
                    title="计划写按设备/组划分,执行记录为按记录随机划分",
                    claim_ids=claim_ids,
                    evidence=_refs(plan_facts) + _refs(exec_facts),
                    missing_evidence=[],
                    suggestion="核对执行代码的划分逻辑:若目标是泛化到新设备,应改为按设备划分(GroupShuffleSplit/groupby)后重新评估。",
                    suggestion_type="fix",
                    reasoning="计划与执行对数据划分的表述直接冲突:计划为组级划分,执行为记录级随机划分。",
                )
            ]
        if plan_record and exec_group and not exec_record:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.CONTRADICTION,
                    title="计划写按记录随机划分,执行记录为按设备/组划分",
                    claim_ids=claim_ids,
                    evidence=_refs(plan_facts) + _refs(exec_facts),
                    missing_evidence=[],
                    suggestion="确认实际采用的划分方式,并更新实验计划使两者一致。",
                    suggestion_type="fix",
                    reasoning="计划与执行对数据划分的表述直接冲突(方向相反)。",
                )
            ]
        return []


class ClaimGeneralizationRule(RuleBase):
    """规则:主张的泛化范围是否被实验划分方式支持。

    例如主张"适用于新设备",则测试集必须由未见过的设备组成;
    若执行为记录级随机划分,同一设备的记录会同时出现在训练与测试集,构成泄漏。
    """

    rule_id = "dm_claim_generalization"
    title = "主张泛化范围与划分方式"

    def check(self, facts, docs, claim_texts, claim_ids):
        # 找出包含"新设备/未见"范围的主张
        target_claims = [
            (cid, text)
            for cid, text in zip(claim_ids, claim_texts)
            if _match_any(text, _NEW_ENTITY_PATTERNS)
        ]
        if not target_claims:
            return []

        grouped = self.group_by_category(facts)
        split_facts = grouped.get(FactCategory.DATA_SPLIT, [])
        target_ids = [cid for cid, _ in target_claims]

        if not split_facts:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.INSUFFICIENT,
                    title="主张涉及新设备泛化,但未提供数据划分信息,无法核实测试集是否为未见设备",
                    claim_ids=target_ids,
                    evidence=[],
                    missing_evidence=["数据划分方式说明或代码", "训练集与测试集的设备编号交集记录"],
                    suggestion="提供数据划分代码或说明,并核对训练集与测试集的设备编号是否相交。",
                    suggestion_type="clarify",
                    reasoning="主张的泛化范围需要划分方式证据支持,目前无法核实。",
                )
            ]

        exec_facts = [f for f in split_facts if docs[f.source.material_id].role == MaterialRole.EXECUTION]
        check_facts = exec_facts or split_facts

        has_group = any(_match_any(f.effective_value(), _GROUP_SPLIT_PATTERNS) for f in check_facts)
        has_record = any(_match_any(f.effective_value(), _RECORD_SPLIT_PATTERNS) for f in check_facts)

        if has_record and not has_group:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.CONTRADICTION,
                    title="主张为预测新设备,但执行为记录级随机划分,同设备记录可能同时进入训练与测试集(数据泄漏)",
                    claim_ids=target_ids,
                    evidence=_refs(check_facts),
                    missing_evidence=["训练集与测试集的设备编号交集记录(用于确认是否泄漏)"],
                    suggestion="核对训练集与测试集的设备编号是否相交;若目标是预测新设备,改为按设备划分后重新评估。若无法重做,可将结论收窄为“在同一批设备上的表现”。",
                    suggestion_type="fix",
                    reasoning="记录级随机划分无法保证测试集由未见设备组成,与“预测新设备”的主张直接冲突。",
                )
            ]
        if has_group:
            # 划分方式与主张一致,但还需设备编号交集证据才能完全确认
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.RISK,
                    title="划分方式为按设备/组,与主张一致,但尚未提供设备编号交集证据",
                    claim_ids=target_ids,
                    evidence=_refs(check_facts),
                    missing_evidence=["训练集与测试集的设备编号交集记录"],
                    suggestion="补充训练集与测试集设备编号的交集检查结果,确认测试集确实只含未见设备。",
                    suggestion_type="clarify",
                    reasoning="划分方式正确,但缺少编号交集的直接证据,尚不能完全排除泄漏。",
                )
            ]
        return []


class RepetitionCheckRule(RuleBase):
    """规则:主张稳定性时是否报告多次运行的波动。"""

    rule_id = "dm_repetition"
    title = "稳定性主张与重复运行证据"

    def check(self, facts, docs, claim_texts, claim_ids):
        target_claims = [
            (cid, text)
            for cid, text in zip(claim_ids, claim_texts)
            if _match_any(text, _STABILITY_PATTERNS)
        ]
        if not target_claims:
            return []
        target_ids = [cid for cid, _ in target_claims]

        grouped = self.group_by_category(facts)
        rep_facts = grouped.get(FactCategory.REPETITION, [])
        has_multi = any(_match_any(f.effective_value(), _MULTI_RUN_PATTERNS) for f in rep_facts)
        has_seed_only = (
            any("seed" in f.effective_value().lower() or "random_state" in f.effective_value().lower() for f in rep_facts)
            and not has_multi
        )

        if has_multi:
            return []
        if has_seed_only:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.RISK,
                    title="主张“更稳定”,但只发现随机种子设置,未见多次运行的波动报告",
                    claim_ids=target_ids,
                    evidence=_refs(rep_facts),
                    missing_evidence=["多次运行的均值±标准差", "重复次数说明"],
                    suggestion="补充多次运行(建议≥5次)的指标均值±标准差;若资源不足,可将结论收窄为“单次运行下的表现”。",
                    suggestion_type="fix",
                    reasoning="稳定性需要多次运行的波动数据支持,单次结果无法体现稳定性。",
                )
            ]
        return [
            Finding(
                rule_id=self.rule_id,
                level=FindingLevel.INSUFFICIENT,
                title="主张“更稳定”,但未提供任何重复运行或随机种子信息",
                claim_ids=target_ids,
                evidence=[],
                missing_evidence=["重复运行次数", "多次运行的均值±标准差"],
                suggestion="说明实验重复次数并提供多次运行的波动数据;或收窄结论。",
                suggestion_type="clarify",
                reasoning="无任何重复性证据,无法核实稳定性主张。",
            )
        ]


class BaselineCheckRule(RuleBase):
    """规则:主张比较关系时是否有基线证据。"""

    rule_id = "dm_baseline"
    title = "比较主张与基线证据"

    def check(self, facts, docs, claim_texts, claim_ids):
        target_claims = [
            (cid, text)
            for cid, text in zip(claim_ids, claim_texts)
            if _match_any(text, _COMPARE_PATTERNS)
        ]
        if not target_claims:
            return []
        target_ids = [cid for cid, _ in target_claims]

        grouped = self.group_by_category(facts)
        baseline_facts = grouped.get(FactCategory.BASELINE, [])
        if not baseline_facts:
            return [
                Finding(
                    rule_id=self.rule_id,
                    level=FindingLevel.INSUFFICIENT,
                    title="主张包含比较关系,但材料中未发现基线/对比方法的运行记录",
                    claim_ids=target_ids,
                    evidence=[],
                    missing_evidence=["基线方法的名称与运行配置", "基线在相同划分与指标下的结果"],
                    suggestion="补充基线方法的运行记录,并确认其在相同数据划分与指标下评估。",
                    suggestion_type="clarify",
                    reasoning="比较主张需要基线在同等条件下的结果才能支持。",
                )
            ]
        return []


class MetricCheckRule(RuleBase):
    """规则:是否提供了评价指标。"""

    rule_id = "dm_metric"
    title = "评价指标完整性"

    def check(self, facts, docs, claim_texts, claim_ids):
        grouped = self.group_by_category(facts)
        metric_facts = grouped.get(FactCategory.METRIC, [])
        if metric_facts:
            return []
        return [
            Finding(
                rule_id=self.rule_id,
                level=FindingLevel.INSUFFICIENT,
                title="未发现任何评价指标,无法评估结论是否被实验支持",
                claim_ids=claim_ids,
                evidence=[],
                missing_evidence=["评价指标的定义与计算方式", "各方法在指标上的具体数值"],
                suggestion="明确评价指标(如准确率、F1、RMSE),并提供各方法的指标数值。",
                suggestion_type="clarify",
                reasoning="没有指标数值,任何“更好/更差”的结论都无法被核实。",
            )
        ]