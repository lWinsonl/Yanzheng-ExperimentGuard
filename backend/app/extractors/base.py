"""事实提取器基类。

提取器的唯一职责:从 ParsedDocument 中提取带原文锚点的事实。
所有 snippet 必须由 make_span_snippet 从原文截取,不得由模型凭记忆生成,
从源头保证 SourceSpan.verify() 必然通过。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.models.evidence import (
    ExtractionSource,
    ExtractedFact,
    FactCategory,
    ParsedDocument,
    SourceSpan,
)

_MATCH_CONTEXT = 80  # 锚点上下文扩展字符数,让片段包含足够语义

# 指标同义词归并表:同一指标的不同写法视为同一事实,避免一条材料出多条 f1
_METRIC_SYNONYMS = {
    "acc": "accuracy",
    "准确率": "accuracy",
    "召回率": "recall",
    "精确率": "precision",
    "f1分数": "f1",
    "f1 分数": "f1",
    "均方根误差": "rmse",
    "平均绝对误差": "mae",
}


def normalize_fact_value(category: FactCategory, value: str) -> str:
    """归一化事实值,用于同类别去重。

    例如 f1_score / f1 / F1 分数 均归并为 f1,同一材料只保留一条;
    baseline.fit / baseline.predict 等同一基线的多次出现只留首条。
    """
    v = value.strip().lower()
    v = re.sub(r"[_-]score$", "", v)  # f1_score -> f1, accuracy_score -> accuracy
    if category == FactCategory.METRIC:
        v = _METRIC_SYNONYMS.get(v, v)
    elif category == FactCategory.BASELINE:
        # 代码中 baseline.fit/predict/赋值/baseline acc= 等视为同一基线线索,只留首条
        parts = v.split()
        v = (parts[0] if parts else v).split("=")[0].split(".")[0].strip()
    return v


def span_from_match(doc: ParsedDocument, m: re.Match) -> SourceSpan:
    """把正则匹配扩展为带上下文的原文锚点。

    扩展上下文是为了让前端展示的 snippet 包含足够的语义(如整行代码/句子),
    但 start/end 仍精确对齐原文,verify 必然通过。
    """
    start = max(0, m.start() - _MATCH_CONTEXT)
    end = min(len(doc.content), m.end() + _MATCH_CONTEXT)
    return SourceSpan(
        material_id=doc.material_id,
        start_char=start,
        end_char=end,
        snippet=doc.content[start:end],
    )


def span_from_range(doc: ParsedDocument, start: int, end: int) -> SourceSpan:
    """由显式区间构造锚点(区间必须基于 doc.content 字符索引)。"""
    start = max(0, min(start, len(doc.content)))
    end = max(start, min(end, len(doc.content)))
    return SourceSpan(
        material_id=doc.material_id,
        start_char=start,
        end_char=end,
        snippet=doc.content[start:end],
    )


class ExtractorBase:
    """提取器基类。"""

    extraction_source: ExtractionSource = ExtractionSource.RULE

    def extract(self, doc: ParsedDocument, session_id: str) -> Iterable[ExtractedFact]:
        raise NotImplementedError

    def make_fact(
        self,
        session_id: str,
        category: FactCategory,
        value: str,
        source: SourceSpan,
        note: str = "",
    ) -> ExtractedFact:
        return ExtractedFact(
            session_id=session_id,
            category=category,
            value=value,
            source=source,
            extraction_source=self.extraction_source,
            note=note,
        )