"""证据链核心数据模型。

设计原则:
1. 每个从材料提取的事实(ExtractedFact)必须携带原文锚点(SourceSpan)。
2. 原文锚点中的 snippet 必须与源文档对应字符区间逐字一致,由 verify_span 校验,
   防止模型幻觉出不存在于原文的"证据"。
3. 事实在被用户确认/纠正/拒绝之前,不进入审查流程(status=pending)。
4. 每个审查发现(Finding)必须引用具体 fact_id,而 fact 又指向 SourceSpan,
   形成 结论 -> 事实 -> 原文片段 的完整证据链。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    """生成带前缀的短 ID,便于日志与前端定位。"""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class MaterialRole(str, Enum):
    """材料归属:计划阶段还是实际执行阶段。两者不一致本身就是重要线索。"""

    PLAN = "plan"          # 实验计划
    EXECUTION = "execution"  # 实际执行(代码、配置、运行结果)


class MaterialKind(str, Enum):
    """材料类型,决定使用哪个解析器。"""

    TEXT = "text"        # 纯文本/Markdown 实验计划
    CODE = "code"        # 代码
    CONFIG = "config"    # 配置文件
    RESULT = "result"    # 运行结果(日志、CSV、JSON)
    PDF = "pdf"          # PDF 文档(扫描件需 OCR,单独标注)


class ParsedDocument(BaseModel):
    """解析后的文档:纯文本 + 字符偏移可定位。

    所有 SourceSpan 的 start_char/end_char 都基于 content 的字符索引,
    这样任何引用都能回溯到原文。
    """

    material_id: str
    role: MaterialRole
    kind: MaterialKind
    filename: str
    content: str
    """解析出的纯文本内容。PDF 扫描件此处为空或部分,见 ocr_required。"""

    ocr_required: bool = False
    """是否需要 OCR/专门解析器。为 True 时 content 不完整,相关事实只能标为
    信息不足,不能假装普通文字提取已覆盖。"""

    ocr_note: str = ""
    """对 OCR 缺口的说明,例如"第3页为扫描表格,未提取"。"""


class SourceSpan(BaseModel):
    """原文位置锚点:证据链的最底层。

    snippet 为冗余存储的原文片段,用于:
    a) 前端无需回查全文即可展示依据;
    b) verify_span 校验该片段确实存在于原文,防止幻觉。
    """

    material_id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    snippet: str

    def verify(self, doc: ParsedDocument) -> bool:
        """校验锚点真实性:snippet 必须与文档对应区间逐字一致。"""
        if self.end_char > len(doc.content) or self.start_char >= self.end_char:
            return False
        return doc.content[self.start_char : self.end_char] == self.snippet


class FactCategory(str, Enum):
    """可核对事实的类别。不同实验类型使用各自的提取规则与审查规则。"""

    COMPARISON_TARGET = "comparison_target"  # 比较对象是什么
    DATA_SPLIT = "data_split"                # 数据如何划分
    METRIC = "metric"                        # 使用了什么指标
    BASELINE = "baseline"                    # 基线怎样运行
    REPETITION = "repetition"                # 重复了几次
    DATASET_DESC = "dataset_desc"            # 数据集描述(规模、来源、设备编号等)
    CLAIM_SCOPE = "claim_scope"              # 主张的适用范围
    OTHER = "other"


class FactStatus(str, Enum):
    """事实确认状态。只有 confirmed/corrected 的事实才进入审查。"""

    PENDING = "pending_user_confirm"  # 待用户确认
    CONFIRMED = "confirmed"           # 用户确认无误
    CORRECTED = "corrected"           # 用户纠正过(以 corrected_value 为准)
    REJECTED = "rejected"             # 用户判定提取错误,不采用


class ExtractionSource(str, Enum):
    """事实由谁提取:规则程序还是模型。便于追溯与评估漏报误报。"""

    RULE = "rule"
    LLM = "llm"


class ExtractedFact(BaseModel):
    """带出处的可核对事实:证据链的中间层。"""

    fact_id: str = Field(default_factory=lambda: new_id("fact"))
    session_id: str
    category: FactCategory
    value: str
    """提取出的结构化值,例如"按 record 随机划分,比例 8:2"。"""

    source: SourceSpan
    """原文锚点。verify 不通过的事实不允许进入审查。"""

    extraction_source: ExtractionSource = ExtractionSource.RULE
    status: FactStatus = FactStatus.PENDING
    corrected_value: str | None = None
    """用户纠正后的值。status=CORRECTED 时审查使用此值。"""

    note: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def effective_value(self) -> str:
        """审查时使用的值:纠正优先。"""
        return self.corrected_value if self.status == FactStatus.CORRECTED else self.value

    def is_usable(self) -> bool:
        """是否可进入审查流程。"""
        return self.status in (FactStatus.CONFIRMED, FactStatus.CORRECTED)


class EvidenceRef(BaseModel):
    """审查发现中对证据的引用,同时携带事实值与原文片段,前端可直接展示。"""

    fact_id: str
    category: FactCategory
    value: str
    source: SourceSpan