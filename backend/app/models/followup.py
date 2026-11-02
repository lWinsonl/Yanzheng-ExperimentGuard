"""基于预期信息价值的追问模型。

设计原则(对应 P1 差异化需求):
1. 从固定缺口清单升级为"回答哪个问题最可能改变审查结论":
   每条追问计算预期信息价值(EIV) = 严重度 × 不确定性 × 可改变概率 ÷ 回答成本。
2. 评分可解释:每条追问携带 score_explanation,展示"为何先问这个"。
3. 每个问题绑定希望获得的证据类型(evidence_type)、格式(evidence_format)
   和对应子主张(sub_claim_id),让用户知道具体要提供什么。
4. 回答追踪:记录哪些答案实际改变了发现(answer_changed_finding),
   用于离线比较排序前后用户完成率、结论变化率与平均追问数。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.evidence import new_id


class EvidenceType(str, Enum):
    """希望用户提供的证据类型。"""

    CODE = "code"            # 代码片段
    CONFIG = "config"        # 配置文件
    RESULT_DATA = "result_data"  # 运行结果数据(CSV/日志/数值)
    EXPLANATION = "explanation"  # 文字说明
    SPLIT_RECORD = "split_record"  # 数据划分记录(编号交集等)
    METRIC_VALUE = "metric_value"  # 指标数值


class AnswerCost(str, Enum):
    """用户回答成本:影响排序(成本越高越往后排)。"""

    LOW = "low"      # 顺手可得(如一句话说明)
    MEDIUM = "medium"  # 需要查找(如翻代码找一行)
    HIGH = "high"    # 需要跑实验(如重新运行并记录)


class FollowupStatus(str, Enum):
    """追问状态。"""

    PENDING = "pending"    # 待回答
    ANSWERED = "answered"  # 已回答
    SKIPPED = "skipped"    # 用户跳过


class FollowupQuestion(BaseModel):
    """一条基于预期信息价值排序的追问。

    评分公式(可解释):
        EIV = severity_score × uncertainty × change_probability / cost_factor

    - severity_score: 目标发现的严重度(contradiction=3, risk=2, insufficient=1)
    - uncertainty: 当前结论的不确定性(0-1,信息越少越高)
    - change_probability: 回答能改变发现的概率(0-1)
    - cost_factor: 回答成本(low=1, medium=2, high=3)
    """

    question_id: str = Field(default_factory=lambda: new_id("fq"))
    session_id: str
    target_finding_id: str = ""
    """目标发现 ID(insufficient 级别的发现)。"""

    target_finding_title: str = ""
    """目标发现标题(冗余存储,前端直接展示)。"""

    sub_claim_id: str = ""
    """绑定的子主张 ID(来自主张-证据图,可为空)。"""

    question: str
    what_to_provide: str = ""
    why_needed: str = ""

    evidence_type: EvidenceType = EvidenceType.EXPLANATION
    evidence_format: str = ""
    """期望的证据格式,例如"代码片段(含行号)"、"CSV 两列:method, F1"。"""

    # ---- 评分因子 ----
    severity_score: float = 1.0
    uncertainty: float = 0.5
    change_probability: float = 0.5
    cost_factor: float = 2.0
    eiv_score: float = 0.0
    """预期信息价值 = severity × uncertainty × change_probability / cost。"""

    score_explanation: str = ""
    """可解释评分:"为何先问这个"——展示各因子如何影响排序。"""

    rank: int = 0
    """排序位置(1 开始,EIV 降序)。"""

    # ---- 回答追踪 ----
    status: FollowupStatus = FollowupStatus.PENDING
    answer_text: str = ""
    answered_at: str = ""
    answer_changed_finding: bool = False
    """回答后重算审查,该目标发现是否发生变化(消除/降级/内容改变)。"""

    finding_change_detail: str = ""
    """发现变化的详细描述,例如"该发现已消除"或"从 risk 降为 insufficient"。"""

    created_at: str = ""


class FollowupStats(BaseModel):
    """追问统计(离线比较用)。

    用于比较排序前后:
    - 用户完成率:answered / (answered + skipped + pending)
    - 结论变化率:changed / answered
    - 平均追问数:total_questions / total_sessions(跨会话)
    """

    total_questions: int = 0
    answered: int = 0
    skipped: int = 0
    pending: int = 0
    changed_findings: int = 0
    """回答后实际改变了发现的次数。"""

    completion_rate: float = 0.0
    """完成率 = answered / total(已回答+已跳过+待回答)。"""

    change_rate: float = 0.0
    """结论变化率 = changed_findings / answered。"""

    avg_questions: float = 0.0
    """平均每会话追问数。"""

    avg_eiv_top: float = 0.0
    """最高 EIV 分数(用于比较排序质量)。"""