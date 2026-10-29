"""证据链核心服务。

职责:把"上传材料"变成"可追溯、可确认的事实"。

处理链(本模块覆盖前三步):
    解析文件 -> 提取带出处的事实 -> 引用校验 -> 存为待确认 -> (用户确认)

引用校验是硬门槛:任何事实的 SourceSpan.verify() 不通过即丢弃,
绝不把无法回溯原文的"事实"交给审查规则。
"""

from __future__ import annotations

import logging

from app.extractors import LlmExtractor, RuleExtractor
from app.models.claim import ReviewSession
from app.models.evidence import (
    ExtractedFact,
    FactStatus,
    MaterialKind,
    MaterialRole,
    ParsedDocument,
)
from app.parsers import get_parser, guess_kind
from app.services.store import SessionStore, data_store

logger = logging.getLogger("evidence_chain")


class EvidenceChainService:
    """证据链服务:材料摄取、事实提取与校验、用户确认。"""

    def __init__(self) -> None:
        self.rule_extractor = RuleExtractor()
        self.llm_extractor = LlmExtractor()

    # ---- 会话 ----
    def create_session(
        self, title: str, experiment_type: str, claim_texts: list[str]
    ) -> ReviewSession:
        from datetime import datetime

        from app.models.claim import Claim, ExperimentType

        try:
            exp_type = ExperimentType(experiment_type)
        except ValueError:
            exp_type = ExperimentType.DATA_MODEL

        claims = [Claim(text=t.strip()) for t in claim_texts if t.strip()]
        session = ReviewSession(
            title=title or "未命名审查",
            experiment_type=exp_type,
            claims=claims,
            created_at=datetime.now().isoformat(),
        )
        data_store.create_session(session)
        return session

    # ---- 材料摄取:解析 + 提取 + 校验 ----
    def ingest_material(
        self,
        session_id: str,
        raw: bytes,
        filename: str,
        role_str: str,
    ) -> tuple[ParsedDocument, list[ExtractedFact], list[str]]:
        """解析材料并提取事实。

        Returns:
            (doc, verified_facts, dropped_reasons)
            dropped_reasons 记录因引用校验失败被丢弃的事实及原因。
        """
        store = data_store.require(session_id)
        role = MaterialRole(role_str) if role_str in ("plan", "execution") else MaterialRole.PLAN
        kind = guess_kind(filename)

        doc = get_parser(kind).parse(raw, filename, role)
        store.docs[doc.material_id] = doc
        store.session.material_ids.append(doc.material_id)

        facts: list[ExtractedFact] = []
        dropped: list[str] = []

        # 规则提取(明确条件交给程序)
        for fact in self.rule_extractor.extract(doc, session_id):
            self._add_verified(store, fact, facts, dropped)
        # 模型提取(复杂上下文,预留;未配密钥时为空)
        for fact in self.llm_extractor.extract(doc, session_id):
            self._add_verified(store, fact, facts, dropped)

        if doc.ocr_required:
            dropped.append(
                f"材料 {filename} 存在未提取内容({doc.ocr_note or '需 OCR'}),"
                "相关事实只能标为信息不足。"
            )

        data_store.persist(session_id)
        return doc, facts, dropped

    def _add_verified(
        self,
        store: SessionStore,
        fact: ExtractedFact,
        accepted: list[ExtractedFact],
        dropped: list[str],
    ) -> None:
        """引用校验硬门槛:verify 不通过即丢弃并记录。"""
        doc = store.docs.get(fact.source.material_id)
        if doc is None or not fact.source.verify(doc):
            reason = f"事实引用校验失败(疑似幻觉),已丢弃:category={fact.category.value} value={fact.value!r}"
            logger.warning(reason)
            dropped.append(reason)
            return
        store.add_fact(fact)
        accepted.append(fact)

    # ---- 用户确认 ----
    def confirm_fact(
        self,
        session_id: str,
        fact_id: str,
        action: str,
        corrected_value: str | None = None,
    ) -> ExtractedFact:
        """用户对提取事实的裁决。

        action: confirm / correct / reject
        """
        store = data_store.require(session_id)
        fact = store.facts.get(fact_id)
        if fact is None:
            raise KeyError(f"事实不存在:{fact_id}")

        if action == "confirm":
            fact.status = FactStatus.CONFIRMED
        elif action == "correct":
            fact.status = FactStatus.CORRECTED
            fact.corrected_value = corrected_value or fact.value
        elif action == "reject":
            fact.status = FactStatus.REJECTED
        else:
            raise ValueError(f"未知操作:{action},应为 confirm/correct/reject")

        data_store.persist(session_id)
        return fact

    def extract_from_text(
        self, session_id: str, text: str, filename: str, role_str: str
    ) -> tuple[ParsedDocument, list[ExtractedFact], list[str]]:
        """便捷方法:直接从文本摄取(前端粘贴内容时使用)。"""
        return self.ingest_material(session_id, text.encode("utf-8"), filename, role_str)


evidence_chain = EvidenceChainService()