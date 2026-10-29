"""审查发现、报告与复查模型。

Finding 是审查输出的核心单元,强制回答四个问题:
1. 依据在哪   -> evidence(引用具体 fact,可回溯原文)
2. 影响哪句结论 -> claim_ids
3. 还缺什么证据 -> missing_evidence
4. 下一步做什么 -> suggestion
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.evidence import EvidenceRef, new_id


class FindingLevel(str, Enum):
    """审查分级。"""

    CONTRADICTION = "contradiction"  # 明确矛盾:计划与执行或主张与证据直接冲突
    RISK = "risk"                    # 潜在风险:迹象可疑但缺完整上下文,尚不能断定
    INSUFFICIENT = "insufficient"    # 信息不足:无法核实,需要补充材料


class Finding(BaseModel):
    """一条审查发现:证据链的顶层输出。"""

    finding_id: str = Field(default_factory=lambda: new_id("find"))
    rule_id: str
    """触发本发现的规则标识,例如 "dm_split_consistency"。"""

    level: FindingLevel
    title: str
    """一句话概括,例如"计划写按设备划分,执行记录为按记录随机划分"。"""

    claim_ids: list[str] = Field(default_factory=list)
    """本发现影响哪些主张。"""

    evidence: list[EvidenceRef] = Field(default_factory=list)
    """依据:引用的具体事实(含原文片段),可逐条回溯。"""

    missing_evidence: list[str] = Field(default_factory=list)
    """还缺什么证据,例如"训练集与测试集的设备编号交集记录"。"""

    suggestion: str = ""
    """下一步具体做什么。资源不足时可建议收窄结论而非一律重做。"""

    suggestion_type: str = "fix"
    """fix=修改实验 / narrow=收窄结论 / clarify=补充说明,默认 fix。"""

    reasoning: str = ""
    """规则的推理过程,让学生看懂为什么触发。"""


class ReviewReport(BaseModel):
    """一次审查的完整报告。"""

    report_id: str = Field(default_factory=lambda: new_id("rpt"))
    session_id: str
    findings: list[Finding] = Field(default_factory=list)
    usable_fact_count: int = 0
    """进入审查的可用事实数(确认/纠正后)。"""

    skipped_fact_count: int = 0
    """因未确认或引用校验失败而跳过的事实数。"""

    created_at: str = ""


class RecheckComparison(BaseModel):
    """复查中单个发现的前后对比。"""

    finding_id: str
    """旧报告中的发现 ID。"""

    rule_id: str
    title: str
    resolved: bool
    """修改后是否不再触发。"""

    new_finding_id: str | None = None
    """若仍触发但内容变化,指向新报告中的对应发现。"""

    note: str = ""
    """说明,例如"已改为按设备划分,该疑点解除"。"""


class RecheckResult(BaseModel):
    """修改复查结果:比较前后版本,显示哪些疑点已解除、哪些仍待核实。"""

    recheck_id: str = Field(default_factory=lambda: new_id("rech"))
    session_id: str
    old_report_id: str
    new_report_id: str
    comparisons: list[RecheckComparison] = Field(default_factory=list)
    newly_raised: list[str] = Field(default_factory=list)
    """新报告中新增的发现 ID(旧报告没有的)。"""

    revision_note: str = ""
    """学生提交的修改理由。"""