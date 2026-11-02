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
        role = MaterialRole(role_str)
        kind = guess_kind(filename)

        from pathlib import PurePosixPath
        from app.parsers.base import EXT_KIND_MAP
        suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
        if suffix and suffix not in EXT_KIND_MAP:
            raise ValueError("不支持此文件格式；请选择文本、代码、CSV、PDF、DOCX或XLSX")
        if raw.startswith(b"PK\x03\x04") and kind not in (MaterialKind.DOCX, MaterialKind.XLSX):
            raise ValueError("文件内容为压缩文档，与扩展名不符，请使用正确的DOCX/XLSX文件名")
        if raw.startswith(b"%PDF") and kind != MaterialKind.PDF:
            raise ValueError("文件内容为PDF，请使用.pdf扩展名")

        doc = get_parser(kind).parse(raw, filename, role)
        if not doc.content.strip() and not doc.ocr_required:
            raise ValueError("材料没有可提取的文字，请检查内容后重新上传")
        store.docs[doc.material_id] = doc
        store.session.material_ids.append(doc.material_id)

        facts: list[ExtractedFact] = []
        dropped: list[str] = []

        # 规则提取(明确条件交给程序)
        for fact in self.rule_extractor.extract(doc, session_id):
            self._add_verified(store, fact, facts, dropped)
        # 模型提取(复杂上下文;未配密钥时降级跳过,与规则提取重叠的自动去重)
        for fact in self.llm_extractor.extract(doc, session_id, existing_facts=facts):
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

    def clear_materials(self, session_id: str, role_str: str, keep_material_id: str | None = None) -> int:
        """删除指定角色的所有材料及其关联事实(替换模式上传前调用)。

        Returns:
            删除的材料数量。
        """
        store = data_store.require(session_id)
        role = MaterialRole(role_str)

        to_remove = [mid for mid, d in store.docs.items() if d.role == role and mid != keep_material_id]
        for mid in to_remove:
            store.archived_docs[mid] = store.docs.pop(mid)
            if mid in store.session.material_ids:
                store.session.material_ids.remove(mid)
        # 级联删除该角色材料关联的所有事实
        fact_ids = [
            fid for fid, f in store.facts.items() if f.source.material_id in to_remove
        ]
        for fid in fact_ids:
            del store.facts[fid]

        # 数据一致性:材料已替换,旧审查报告/复查结果/主张-证据图/追问引用的事实已不存在,一并清除。
        # 否则报告页点"查看原文"会 404,复查对比、证据图与追问也会引用已删除的事实。
        # 数据一致性:材料已替换,主张-证据图/追问/版本差异/迁移引用的事实已不存在,一并清除。
        # 注意:旧审查报告与复查结果保留——版本差异复审需要历史报告做对比(P2)。
        # 旧报告中的 evidence ref 携带冗余值与片段,前端展示不受影响;仅"查看原文"对已删材料不可用。
        if to_remove and (store.claim_graph or store.followup_questions or store.version_diffs or store.migration_questions):
            logger.info(
                "替换模式:同步清除会话 %s 的主张-证据图、追问、版本差异与迁移数据(材料已替换,引用的事实已不存在;旧报告保留供版本对比)",
                session_id,
            )
            store.claim_graph = None
            store.followup_questions = []
            store.version_diffs = []
            store.migration_questions = []
            store.migration_answers = []
            store.manual_labels = []

        if to_remove:
            logger.info("替换模式:清除会话 %s 的 %s 材料 %d 份、关联事实 %d 条",
                        session_id, role.value, len(to_remove), len(fact_ids))
            data_store.persist(session_id)
        return len(to_remove)


evidence_chain = EvidenceChainService()
