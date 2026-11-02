"""主张—证据图模型:把主张拆成可检验子主张,与证据显式连接。

设计原则(对应 P0 差异化需求):
1. 每条边(ClaimEvidenceEdge)必须绑定已验证锚点(用户确认/纠正的事实,
   其 SourceSpan 已通过 verify),规则构建的边不允许引用未验证事实。
2. 每条边显式声明关系类型(supports/contradicts/unknown)及其依据(basis),
   不允许只给结论不给理由。
3. 反证检查(CounterEvidenceCheck)严格区分三种状态:
   - no_counter_found: 没有找到反证(不等于证明不存在反证)
   - counter_refuted:  反证被排除(有直接证据证明反证不成立)
   - counter_exists:   存在反证(材料中出现了与子主张矛盾的证据)
4. 模型(LLM)只提出候选边(source=llm, status=pending),
   需用户确认后才生效;规则构建的边为确定性输出。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.evidence import new_id


class TestAspect(str, Enum):
    """子主张的检验维度:决定它需要哪类证据。"""

    __test__ = False  # 告知 pytest 不要把本类当测试类收集

    SCOPE = "scope"                # 适用范围:测试集是否真的由未见实体组成
    COMPARISON = "comparison"      # 比较关系:指标是否真的优于基线
    STABILITY = "stability"        # 稳定性:多次运行是否保持优势
    BASELINE_FAIRNESS = "baseline_fairness"  # 基线公平:基线是否在同等条件下评估
    METRIC_AVAIL = "metric_avail"  # 指标可用:是否提供了可核实的评价指标


class EdgeRelation(str, Enum):
    """边的关系类型:证据对子主张的支持方向。"""

    SUPPORTS = "supports"        # 证据支持子主张
    CONTRADICTS = "contradicts"  # 证据与子主张矛盾
    UNKNOWN = "unknown"          # 无法判定(信息不足)


class EvidenceDirection(str, Enum):
    """证据来源方向:标明这条边从哪个阶段/类型的材料得出。"""

    PLAN = "plan"                # 来自实验计划
    EXECUTION = "execution"      # 来自实际执行(代码/配置)
    RESULT = "result"            # 来自运行结果
    COUNTER = "counter"          # 反证方向
    MISSING_PREMISE = "missing_premise"  # 缺失前提(无可绑定事实)


class EdgeSource(str, Enum):
    """边的构建来源:规则(确定性)还是模型(候选)。"""

    RULE = "rule"
    LLM = "llm"


class EdgeStatus(str, Enum):
    """边的用户校准状态。规则边默认 confirmed;模型候选边默认 pending。"""

    PENDING = "pending_user_confirm"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class SubClaim(BaseModel):
    """从主张拆出的可检验子主张。

    例如主张"模型A比基线B更能预测新设备的故障,且更稳定"可拆出:
    - scope:      "测试集由训练时未见过的设备组成"
    - comparison: "模型A在评价指标上优于基线B"
    - stability:  "该优势在多次运行中保持稳定"
    """

    sub_claim_id: str = Field(default_factory=lambda: new_id("sub"))
    claim_id: str
    """所属父主张 ID。"""

    text: str
    """子主张的可检验表述。"""

    test_aspect: TestAspect
    """检验维度,决定需要哪类证据。"""

    scope_keywords: list[str] = Field(default_factory=list)
    """适用范围关键词,例如 ["新设备"]。"""

    source: EdgeSource = EdgeSource.RULE
    """拆出来源:规则(确定性)或模型(候选)。"""

    status: EdgeStatus = EdgeStatus.CONFIRMED
    """用户校准状态。规则拆出的默认 confirmed;模型候选默认 pending。"""


class ClaimEvidenceEdge(BaseModel):
    """主张—证据图中的一条边:连接子主张与已验证事实。

    每条边回答四个问题:
    1. 连接什么   -> sub_claim_id + fact_id
    2. 什么关系   -> relation (supports/contradicts/unknown)
    3. 为什么     -> basis (依据说明)
    4. 从哪来的   -> direction (plan/execution/result/counter/missing_premise)
    """

    edge_id: str = Field(default_factory=lambda: new_id("edge"))
    sub_claim_id: str
    fact_id: str | None = None
    """绑定的已验证事实 ID。direction=missing_premise 时为 None。"""

    relation: EdgeRelation
    basis: str
    """为什么是这个关系:一句话说明依据。"""

    direction: EvidenceDirection
    scope: str = ""
    """本边适用的范围限定,例如"在当前数据集上"。"""

    source: EdgeSource = EdgeSource.RULE
    status: EdgeStatus = EdgeStatus.CONFIRMED
    """用户校准状态。规则边绑定已验证锚点,默认 confirmed。"""

    corrected_relation: EdgeRelation | None = None
    """用户纠正后的关系。status=CORRECTED 时以此为准。"""

    def effective_relation(self) -> EdgeRelation:
        """校准后实际生效的关系:纠正优先。"""
        return self.corrected_relation if self.status == EdgeStatus.CORRECTED and self.corrected_relation else self.relation

    def is_active(self) -> bool:
        """是否生效:未拒绝的边参与图的整体判断。"""
        return self.status != EdgeStatus.REJECTED


class CounterProofStatus(str, Enum):
    """反证检查的三种状态(核心认识论区分)。

    - no_counter_found: 没有找到反证。含义:在已有材料中未发现矛盾证据,
      但这**不等于**证明了不存在反证——可能只是材料没覆盖到。
    - counter_refuted: 反证被排除。含义:有直接证据证明反证不成立
      (例如提供了训练/测试设备编号无交集的检查结果)。
    - counter_exists: 存在反证。含义:材料中出现了与子主张矛盾的证据
      (例如发现了同设备记录同时进入训练与测试集)。
    """

    NO_COUNTER_FOUND = "no_counter_found"
    COUNTER_REFUTED = "counter_refuted"
    COUNTER_EXISTS = "counter_exists"


class CounterEvidenceCheck(BaseModel):
    """反证与替代解释检查。

    对每个子主张,显式检查:
    1. 有没有替代解释能同样符合现有证据?
    2. 有没有反证?是"没找到"还是"证明了不存在"?
    """

    check_id: str = Field(default_factory=lambda: new_id("cchk"))
    sub_claim_id: str
    alternative_explanation: str
    """替代解释:同样能符合现有证据的另一种说法。"""

    proof_status: CounterProofStatus
    basis: str
    """状态判定依据:为什么是 no_counter_found / counter_refuted / counter_exists。"""

    fact_ids: list[str] = Field(default_factory=list)
    """支撑本判定的已验证事实 ID。"""

    missing_to_prove_absence: list[str] = Field(default_factory=list)
    """若要把"没找到反证"升级为"证明不存在反证",还需要什么证据。"""


class ClaimGraph(BaseModel):
    """一次会话的完整主张—证据图。"""

    graph_id: str = Field(default_factory=lambda: new_id("graph"))
    session_id: str
    sub_claims: list[SubClaim] = Field(default_factory=list)
    edges: list[ClaimEvidenceEdge] = Field(default_factory=list)
    counter_checks: list[CounterEvidenceCheck] = Field(default_factory=list)
    created_at: str = ""

    # ---- 查询工具 ----

    def sub_claim_by_id(self, sub_claim_id: str) -> SubClaim | None:
        for sc in self.sub_claims:
            if sc.sub_claim_id == sub_claim_id:
                return sc
        return None

    def edges_for_sub_claim(self, sub_claim_id: str) -> list[ClaimEvidenceEdge]:
        return [e for e in self.edges if e.sub_claim_id == sub_claim_id and e.is_active()]

    def counter_check_for_sub_claim(self, sub_claim_id: str) -> CounterEvidenceCheck | None:
        for cc in self.counter_checks:
            if cc.sub_claim_id == sub_claim_id:
                return cc
        return None

    def sub_claims_for_claim(self, claim_id: str) -> list[SubClaim]:
        return [sc for sc in self.sub_claims if sc.claim_id == claim_id]

    def active_edge_count(self) -> int:
        return len([e for e in self.edges if e.is_active()])

    def supports_count(self) -> int:
        return len([e for e in self.edges if e.is_active() and e.effective_relation() == EdgeRelation.SUPPORTS])

    def contradicts_count(self) -> int:
        return len([e for e in self.edges if e.is_active() and e.effective_relation() == EdgeRelation.CONTRADICTS])

    def unknown_count(self) -> int:
        return len([e for e in self.edges if e.is_active() and e.effective_relation() == EdgeRelation.UNKNOWN])