"""规则事实提取器。

用正则从实验计划(中文文本)与代码/结果(英文)中提取可核对事实。
每条事实的 snippet 均由 span_from_match 从原文截取,verify 必然通过。

覆盖的事实类别:
- DATA_SPLIT      数据划分方式(随机/按组/按设备,比例,有无 stratify)
- METRIC          评价指标
- BASELINE        基线方法
- REPETITION      重复运行与随机种子
- DATASET_DESC    数据集描述(设备编号、规模)
- COMPARISON_TARGET 比较对象
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.models.evidence import ExtractedFact, FactCategory, ParsedDocument
from app.extractors.base import ExtractorBase, normalize_fact_value, span_from_match


def _iter_matches(pattern: str, text: str, flags: int = 0):
    """去重地迭代所有匹配(同一位置只取一次)。"""
    seen: set[tuple[int, int]] = set()
    for m in re.finditer(pattern, text, flags):
        key = (m.start(), m.end())
        if key not in seen:
            seen.add(key)
            yield m


class RuleExtractor(ExtractorBase):
    """规则提取器:明确条件交给程序,不依赖模型。"""

    # ---- 数据划分 ----
    SPLIT_PATTERNS: list[tuple[str, str]] = [
        # 代码:scikit-learn 划分
        (r"train_test_split\s*\([^)]*\)", "代码中出现 train_test_split(记录级随机划分的典型信号)"),
        (r"GroupShuffleSplit\s*\([^)]*\)", "代码中出现 GroupShuffleSplit(按组划分)"),
        (r"GroupKFold\s*\([^)]*\)", "代码中出现 GroupKFold(按组交叉验证)"),
        (r"test_size\s*=\s*[\d.]+", "代码中指定了测试集比例"),
        (r"stratify\s*=", "代码划分时使用了 stratify"),
        # 中文计划
        (r"按\s*(设备|机器|机组|单元|组|用户|病人|被试)[^,。;。\n]{0,12}(划分|切分|分割|分组)",
         "计划中写明按设备/组划分"),
        (r"(随机|按记录|按样本|按条)[^,。;。\n]{0,10}(划分|切分|分割|split)",
         "计划/记录中写明按记录随机划分"),
    ]

    # ---- 指标 ----
    METRIC_PATTERNS: list[tuple[str, str]] = [
        (r"\b(accuracy|acc|precision|recall|f1[_-]?score|f1|auc|auroc|rmse|mse|mae|map|ndcg)\b",
         "出现评价指标"),
        (r"(准确率|精确率|召回率|F1[分数值]?|AUC|均方根误差|平均绝对误差)",
         "出现评价指标(中文)"),
    ]

    # ---- 基线 ----
    BASELINE_PATTERNS: list[tuple[str, str]] = [
        (r"(基线|对比方法|参照方法|baseline)[^。\n]{0,60}", "提及基线/对比方法"),
        (r"(compare[d]?\s+(with|to|against)|compared\s+with|vs\.?)\s+\w+", "代码/结果中与某方法对比"),
    ]

    # ---- 重复性 ----
    REPETITION_PATTERNS: list[tuple[str, str]] = [
        (r"(random_state|seed|manual_seed|np\.random\.seed|torch\.manual_seed)\s*[=\(]\s*[\w]+",
         "代码设置了随机种子(单次运行信号)"),
        (r"(重复|运行|实验)[^。\n]{0,6}(\d+)\s*次", "声明重复运行次数"),
        (r"(mean\s*[±+/-]\s*std|均值\s*[±]\s*标准差|±\s*[\d.]+)", "报告了均值±标准差(多次运行信号)"),
        (r"\bn[_-]?runs\s*=\s*\d+|n_repeats\s*=\s*\d+", "代码指定重复次数"),
    ]

    # ---- 数据集描述 ----
    DATASET_PATTERNS: list[tuple[str, str]] = [
        (r"(设备|机器|机组|装置|device|machine|unit)\s*(编号|ID|id|号)[^。\n]{0,40}",
         "提及设备编号/ID"),
        (r"(共|总计|合计)?\s*(\d+)\s*(条|个|台|台设备|个样本|条记录|samples?|records?)",
         "提及数据规模"),
    ]

    # ---- 比较对象 ----
    COMPARISON_PATTERNS: list[tuple[str, str]] = [
        (r"(比|优于|超过|好于|强于|outperform[s]?|better\s+than|superior\s+to)[^。\n]{0,60}",
         "主张中出现的比较关系"),
    ]

    def extract(self, doc: ParsedDocument, session_id: str) -> Iterable[ExtractedFact]:
        if doc.ocr_required and not doc.content:
            # 无可提取文本,不产出事实;审查规则会标为信息不足
            return []

        yield from self._extract_category(
            doc, session_id, FactCategory.DATA_SPLIT, self.SPLIT_PATTERNS
        )
        yield from self._extract_category(
            doc, session_id, FactCategory.METRIC, self.METRIC_PATTERNS
        )
        yield from self._extract_category(
            doc, session_id, FactCategory.BASELINE, self.BASELINE_PATTERNS
        )
        yield from self._extract_category(
            doc, session_id, FactCategory.REPETITION, self.REPETITION_PATTERNS
        )
        yield from self._extract_category(
            doc, session_id, FactCategory.DATASET_DESC, self.DATASET_PATTERNS
        )
        yield from self._extract_category(
            doc, session_id, FactCategory.COMPARISON_TARGET, self.COMPARISON_PATTERNS
        )

    def _extract_category(
        self,
        doc: ParsedDocument,
        session_id: str,
        category: FactCategory,
        patterns: list[tuple[str, str]],
    ) -> Iterable[ExtractedFact]:
        seen: set[str] = set()  # 同类别归一化值去重(如 f1_score 与 f1 只留一条)
        for pattern, note in patterns:
            for m in _iter_matches(pattern, doc.content, re.IGNORECASE):
                value = m.group(0).strip()
                norm = normalize_fact_value(category, value)
                if norm in seen:
                    continue
                seen.add(norm)
                yield self.make_fact(
                    session_id=session_id,
                    category=category,
                    value=value,
                    source=span_from_match(doc, m),
                    note=note,
                )