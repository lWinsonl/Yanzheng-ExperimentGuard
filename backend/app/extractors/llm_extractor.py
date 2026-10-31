"""模型事实提取器(含引用校验防幻觉)。

与规则提取器的根本区别:模型可能幻觉出不存在的"原文引用"。
因此本提取器强制执行两道校验,任何一道不通过即丢弃该事实:

1. schema 校验:模型输出必须符合固定 JSON 结构(类别/值/引用片段);
2. 引用校验:模型给出的 quote 必须能在源文档中逐字找到,
   并据此换算出真实的 start_char/end_char。
   找不到则判定为幻觉,事实不进入确认流程。

调用链:llm_client.chat() -> _parse_json -> _build_verified_fact(引用校验)。
未配置模型密钥时 is_available() 返回 False,直接返回空(降级到规则提取)。
与规则提取器重叠的事实(同类别且原文区间重叠)自动去重。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from app.models.evidence import (
    ExtractionSource,
    ExtractedFact,
    FactCategory,
    ParsedDocument,
    SourceSpan,
)
from app.extractors.base import ExtractorBase, normalize_fact_value, span_from_range

# 模型输出的固定 JSON schema 说明(写入 prompt)
LLM_FACT_SCHEMA = {
    "facts": [
        {
            "category": "data_split|metric|baseline|repetition|dataset_desc|comparison_target|claim_scope|other",
            "value": "结构化的事实值",
            "quote": "必须逐字复制自原文的片段,不得改写",
        }
    ]
}

SYSTEM_PROMPT = (
    "你是实验审查助手。从给定材料中提取可核对的事实。\n"
    "事实类别(category)只能是以下之一:\n"
    "- data_split: 数据划分方式(如 train_test_split、按设备划分、交叉验证)\n"
    "- metric: 评价指标(如 accuracy、F1、RMSE)\n"
    "- baseline: 基线/对比方法\n"
    "- repetition: 重复运行次数、随机种子、均值±标准差\n"
    "- dataset_desc: 数据集描述(规模、来源、设备编号)\n"
    "- comparison_target: 比较对象(优于/超过某方法)\n"
    "- claim_scope: 主张的适用范围\n"
    "- other: 其他可核对事实\n\n"
    "严格输出 JSON,结构为:{"
    '"facts":[{"category":"...","value":"...","quote":"..."}]'
    "}\n"
    "value 用简洁中文概括事实;"
    "quote 必须逐字复制自原文,不得改写、翻译或缩写;"
    "若某信息无法从原文逐字引用,不要输出该事实。\n"
    "只输出 JSON,不要输出其他内容。"
)


class LlmExtractor(ExtractorBase):
    """模型提取器:输出固定格式 + 引用逐字校验,双保险防幻觉。"""

    extraction_source = ExtractionSource.LLM
    _llm_client = None  # 延迟注入,避免与 agent_service 循环导入

    @classmethod
    def _client(cls):
        """延迟获取 llm_client 单例(避免 extractors->agent->services 循环导入)。"""
        if cls._llm_client is None:
            from app.agent.llm_client import llm_client

            cls._llm_client = llm_client
        return cls._llm_client

    def extract(
        self,
        doc: ParsedDocument,
        session_id: str,
        existing_facts: list[ExtractedFact] | None = None,
    ) -> Iterable[ExtractedFact]:
        if not self._client().is_available():
            # 未配置模型密钥:规则提取已覆盖,模型提取降级跳过
            return []
        if doc.ocr_required and not doc.content:
            return []

        raw_output = self._call_llm(doc)
        if not raw_output:
            return []

        facts_data = self._parse_json(raw_output)
        if not facts_data:
            return []

        # 去重索引:同类别且原文区间重叠,或归一化值相同,视为规则已提取过
        existing_spans: list[tuple[FactCategory, int, int]] = [
            (f.category, f.source.start_char, f.source.end_char)
            for f in (existing_facts or [])
            if f.source.material_id == doc.material_id
        ]
        existing_norms: set[str] = {
            normalize_fact_value(f.category, f.value)
            for f in (existing_facts or [])
            if f.source.material_id == doc.material_id
        }

        seen: set[str] = set()  # 模型自身输出去重
        for item in facts_data:
            fact = self._build_verified_fact(doc, session_id, item)
            if fact is None:
                continue
            norm = normalize_fact_value(fact.category, fact.value)
            if norm in existing_norms or norm in seen:
                continue  # 与规则提取或自身重复,跳过
            if any(
                cat == fact.category
                and not (fact.source.end_char <= s or fact.source.start_char >= e)
                for cat, s, e in existing_spans
            ):
                continue  # 与规则提取区间重叠,跳过
            seen.add(norm)
            yield fact

    def _call_llm(self, doc: ParsedDocument) -> str:
        """调用模型提取事实。失败返回空字符串(降级到规则提取结果)。"""
        user_prompt = (
            f"材料文件名:{doc.filename}\n"
            f"材料类型:{doc.kind.value}\n"
            f"材料内容:\n{doc.content}"
        )
        raw = self._client().chat(
            SYSTEM_PROMPT, user_prompt, temperature=0.1, max_tokens=2000
        )
        return raw or ""

    @staticmethod
    def _parse_json(raw: str) -> list[dict] | None:
        """解析模型输出为 JSON,容错处理 markdown 代码块包裹。"""
        text = raw.strip()
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and isinstance(data.get("facts"), list):
            return data["facts"]
        if isinstance(data, list):
            return data
        return None

    def _build_verified_fact(
        self, doc: ParsedDocument, session_id: str, item: dict
    ) -> ExtractedFact | None:
        """schema + 引用双重校验。校验失败返回 None(丢弃幻觉事实)。"""
        category_str = str(item.get("category", "")).strip()
        value = str(item.get("value", "")).strip()
        quote = str(item.get("quote", "")).strip()
        if not category_str or not value or not quote:
            return None

        try:
            category = FactCategory(category_str)
        except ValueError:
            category = FactCategory.OTHER

        # 引用校验:quote 必须逐字存在于原文
        idx = doc.content.find(quote)
        if idx < 0:
            # 幻觉引用:丢弃,不进入确认流程
            return None

        source = span_from_range(doc, idx, idx + len(quote))
        return self.make_fact(
            session_id=session_id,
            category=category,
            value=value,
            source=source,
            note="模型提取,引用已校验",
        )