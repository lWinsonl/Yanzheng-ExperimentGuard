"""模型事实提取器(预留接口,含引用校验)。

与规则提取器的根本区别:模型可能幻觉出不存在的"原文引用"。
因此本提取器强制执行两道校验,任何一道不通过即丢弃该事实:

1. schema 校验:模型输出必须符合固定 JSON 结构(类别/值/引用片段);
2. 引用校验:模型给出的 quote 必须能在源文档中逐字找到,
   并据此换算出真实的 start_char/end_char。
   找不到则判定为幻觉,事实不进入确认流程。

骨架阶段不实际调用模型(未配置 API 密钥时直接返回空),
但校验逻辑已完整实现,供后续接入模型时直接使用。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from app.config import settings
from app.models.evidence import (
    ExtractionSource,
    ExtractedFact,
    FactCategory,
    ParsedDocument,
    SourceSpan,
)
from app.extractors.base import ExtractorBase, span_from_range

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
    "你是实验审查助手。从给定材料中提取可核对的事实。"
    "严格输出 JSON,结构为:{"
    '"facts":[{"category":"...","value":"...","quote":"..."}]'
    "}。"
    "quote 必须逐字复制自原文,不得改写、翻译或缩写;"
    "若某信息无法从原文逐字引用,不要输出该事实。"
    "只输出 JSON,不要输出其他内容。"
)


class LlmExtractor(ExtractorBase):
    """模型提取器:输出固定格式 + 引用逐字校验,双保险防幻觉。"""

    extraction_source = ExtractionSource.LLM

    def extract(self, doc: ParsedDocument, session_id: str) -> Iterable[ExtractedFact]:
        if not settings.llm_api_key:
            # 未配置模型密钥:规则先行,模型提取暂不启用
            return []
        if doc.ocr_required and not doc.content:
            return []

        raw_output = self._call_llm(doc)
        if not raw_output:
            return []

        facts_data = self._parse_json(raw_output)
        if not facts_data:
            return []

        for item in facts_data:
            fact = self._build_verified_fact(doc, session_id, item)
            if fact is not None:
                yield fact

    def _call_llm(self, doc: ParsedDocument) -> str:
        """调用模型。预留:实际项目接 openai/httpx,密钥仅在服务端使用。"""
        # 骨架阶段返回空,避免无密钥时报错
        return ""

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