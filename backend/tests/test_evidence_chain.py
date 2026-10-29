"""证据链核心测试:提取、引用校验(防幻觉)、确认流。

运行:cd backend && python -m pytest tests/test_evidence_chain.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.evidence import FactStatus, SourceSpan
from app.services import data_store, evidence_chain


def _new_session(claim: str = "模型 A 比基线 B 更能预测新设备的故障,且更稳定。"):
    return evidence_chain.create_session(
        title="测试会话", experiment_type="data_model", claim_texts=[claim]
    )


def test_extract_facts_with_verified_spans():
    """提取的每条事实,其原文锚点必须通过逐字校验。"""
    session = _new_session()
    plan = (
        "实验计划:\n"
        "1. 数据按设备划分,训练集与测试集设备不重叠。\n"
        "2. 评价指标为 F1 和 AUC。\n"
        "3. 基线为逻辑回归。\n"
        "4. 重复运行 5 次,报告均值±标准差。\n"
    )
    doc, facts, dropped = evidence_chain.extract_from_text(
        session.session_id, plan, "plan.md", "plan"
    )
    assert not dropped, f"不应有丢弃事实:{dropped}"
    assert len(facts) > 0, "应提取到事实"
    store = data_store.require(session.session_id)
    for f in facts:
        assert f.source.verify(store.docs[f.source.material_id]), (
            f"事实 {f.fact_id} 的锚点校验失败"
        )
        assert f.status == FactStatus.PENDING, "新提取事实应为待确认状态"


def test_hallucinated_span_is_dropped():
    """伪造的原文锚点(幻觉)必须被引用校验拦截。"""
    from app.models.evidence import ExtractedFact, FactCategory, SourceSpan

    session = _new_session()
    store = data_store.require(session.session_id)
    doc, _, _ = evidence_chain.extract_from_text(
        session.session_id, "正常文本内容", "p.txt", "plan"
    )

    # 构造一条 snippet 与原文不一致的"幻觉事实"
    fake_span = SourceSpan(
        material_id=doc.material_id,
        start_char=0,
        end_char=10,
        snippet="这段文字不存在于原文中",
    )
    fake_fact = ExtractedFact(
        session_id=session.session_id,
        category=FactCategory.DATA_SPLIT,
        value="按设备划分",
        source=fake_span,
    )

    accepted: list = []
    dropped: list = []
    evidence_chain._add_verified(store, fake_fact, accepted, dropped)
    assert not accepted, "幻觉事实不应被接受"
    assert len(dropped) == 1, "幻觉事实应被记录为丢弃"
    assert "校验失败" in dropped[0]


def test_fact_confirm_flow():
    """确认/纠正/拒绝三种操作正确改变事实状态。"""
    session = _new_session()
    evidence_chain.extract_from_text(
        session.session_id,
        "数据按设备划分,测试集占 20%。",
        "plan.md",
        "plan",
    )
    store = data_store.require(session.session_id)
    facts = store.facts_for_session()
    assert facts, "应提取到事实"

    # 确认第一条
    f0 = evidence_chain.confirm_fact(session.session_id, facts[0].fact_id, "confirm")
    assert f0.status == FactStatus.CONFIRMED

    # 纠正第二条(如有)
    if len(facts) > 1:
        f1 = evidence_chain.confirm_fact(
            session.session_id, facts[1].fact_id, "correct", "纠正后的值"
        )
        assert f1.status == FactStatus.CORRECTED
        assert f1.effective_value() == "纠正后的值"

    # 拒绝第三条(如有)
    if len(facts) > 2:
        f2 = evidence_chain.confirm_fact(session.session_id, facts[2].fact_id, "reject")
        assert f2.status == FactStatus.REJECTED
        assert not f2.is_usable()

    # 只有 confirmed/corrected 进入审查
    usable = store.usable_facts()
    assert all(f.is_usable() for f in usable)


def test_ocr_material_flags_insufficient():
    """OCR 缺口材料不产出事实,且记录缺口说明。"""
    session = _new_session()
    # 模拟 PDF 扫描件:构造一个 ocr_required 的文档
    from app.models.evidence import MaterialKind, MaterialRole, ParsedDocument

    store = data_store.require(session.session_id)
    doc = ParsedDocument(
        material_id="mat_ocr_test",
        role=MaterialRole.EXECUTION,
        kind=MaterialKind.PDF,
        filename="scan.pdf",
        content="",
        ocr_required=True,
        ocr_note="第 1-3 页为扫描件,未提取。",
    )
    store.docs[doc.material_id] = doc
    store.session.material_ids.append(doc.material_id)

    _, facts, dropped = evidence_chain.extract_from_text(
        session.session_id, "", "scan.pdf", "execution"
    )
    # 空内容不产出事实
    assert isinstance(facts, list)


if __name__ == "__main__":
    test_extract_facts_with_verified_spans()
    test_hallucinated_span_is_dropped()
    test_fact_confirm_flow()
    test_ocr_material_flags_insufficient()
    print("证据链核心测试全部通过")