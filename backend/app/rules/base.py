"""审查规则基类。

规则程序处理明确条件,模型处理需要理解上下文的部分(后续接入)。
每条规则只做一件事:检查某一类"主张-实验-证据"对应关系,
输出 Finding(明确矛盾 / 潜在风险 / 信息不足)。

规则的输入只包含用户已确认/纠正的事实(is_usable),
未经确认的猜测不作为审查依据。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict

from app.models.claim import ExperimentType
from app.models.evidence import ExtractedFact, FactCategory, ParsedDocument
from app.models.review import Finding


class RuleBase(ABC):
    """审查规则基类。"""

    rule_id: str = ""
    title: str = ""
    experiment_type: ExperimentType = ExperimentType.DATA_MODEL

    @abstractmethod
    def check(
        self,
        facts: list[ExtractedFact],
        docs: dict[str, ParsedDocument],
        claim_texts: list[str],
        claim_ids: list[str],
    ) -> list[Finding]:
        """执行检查,返回发现列表(可为空)。

        Args:
            facts: 已确认/纠正的可用事实。
            docs: material_id -> 文档,用于构造证据引用与判断材料缺口。
            claim_texts: 主张原文列表,与 claim_ids 一一对应。
            claim_ids: 主张 ID 列表。
        """
        raise NotImplementedError

    # ---- 工具方法 ----

    @staticmethod
    def group_by_category(
        facts: list[ExtractedFact],
    ) -> dict[FactCategory, list[ExtractedFact]]:
        grouped: dict[FactCategory, list[ExtractedFact]] = defaultdict(list)
        for f in facts:
            grouped[f.category].append(f)
        return grouped

    @staticmethod
    def has_plan_and_execution(docs: dict[str, ParsedDocument]) -> tuple[bool, bool]:
        """判断是否同时提供了计划类与执行类材料。"""
        has_plan = any(d.role.value == "plan" for d in docs.values())
        has_exec = any(d.role.value == "execution" for d in docs.values())
        return has_plan, has_exec


def get_rules_for(experiment_type: ExperimentType) -> list[RuleBase]:
    """按实验类型返回规则集。"""
    from app.rules.algorithm_system_rules import (
        BaselineCheckRule as ASBaselineCheckRule,
        MetricCheckRule as ASMetricCheckRule,
        PlanExecutionCoverageRule,
        StabilityRepetitionRule,
    )
    from app.rules.data_model_rules import (
        BaselineCheckRule,
        ClaimGeneralizationRule,
        MetricCheckRule,
        RepetitionCheckRule,
        SplitConsistencyRule,
    )

    all_rules: list[RuleBase] = [
        # 数据与模型实验
        SplitConsistencyRule(),
        ClaimGeneralizationRule(),
        RepetitionCheckRule(),
        BaselineCheckRule(),
        MetricCheckRule(),
        # 算法与系统性能实验
        ASBaselineCheckRule(),
        ASMetricCheckRule(),
        StabilityRepetitionRule(),
        PlanExecutionCoverageRule(),
    ]
    return [r for r in all_rules if r.experiment_type == experiment_type]