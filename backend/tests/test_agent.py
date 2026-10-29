"""智能体降级模式测试:无 LLM 密钥时,所有能力降级到启发式规则。

运行:cd backend && python -m pytest tests/test_agent.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.agent_service import agent_service
from app.agent.llm_client import llm_client
from app.services import data_store, evidence_chain, review_service


CLAIM = "模型 A 比基线 B 更能预测新设备的故障,且更稳定。"


def _setup_with_materials():
    """创建会话并上传计划+执行材料(有漏洞案例)。"""
    session = evidence_chain.create_session(
        title="智能体测试", experiment_type="data_model", claim_texts=[CLAIM]
    )
    evidence_chain.extract_from_text(
        session.session_id,
        "实验计划:数据按设备划分,训练集与测试集设备编号不重叠。指标 F1。基线逻辑回归。重复 5 次报告均值±标准差。",
        "plan.md",
        "plan",
    )
    evidence_chain.extract_from_text(
        session.session_id,
        "from sklearn.model_selection import train_test_split\n"
        "X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)\n",
        "train.py",
        "execution",
    )
    store = data_store.require(session.session_id)
    for f in store.facts_for_session():
        if f.status.value == "pending_user_confirm":
            evidence_chain.confirm_fact(session.session_id, f.fact_id, "confirm")
    return session.session_id


def test_llm_unavailable_uses_heuristic():
    """无密钥时,智能体明确处于启发式降级模式。"""
    assert not llm_client.is_available(), "测试环境不应有 LLM 密钥"


def test_heuristic_direction_analysis():
    """启发式方向审查:能从主张关键词推断实验设计要求。"""
    session_id = _setup_with_materials()
    result = agent_service.analyze_direction(session_id)

    assert result.source == "heuristic"
    assert result.claim_clarity == "clear", "主张含比较+泛化+稳定性,应判定为清晰"
    # 应推断出泛化要求(新设备)
    req_texts = " ".join(r["requirement"] for r in result.design_requirements)
    assert "未见过的设备" in req_texts or "按组划分" in req_texts, (
        f"应推断出按组划分要求,实际:{req_texts}"
    )
    # 应推断出稳定性要求
    assert any("多次运行" in r["requirement"] for r in result.design_requirements), (
        "应推断出多次运行要求"
    )
    # 应推断出基线要求
    assert any("基线" in r["requirement"] for r in result.design_requirements), (
        "应推断出基线要求"
    )


def test_heuristic_gap_analysis():
    """启发式缺口分析:能发现缺什么材料。"""
    session_id = _setup_with_materials()
    result = agent_service.analyze_gaps(session_id)

    assert result.source == "heuristic"
    assert result.sufficiency in ("sufficient", "partial", "insufficient")
    # 有计划+有执行+有划分+有指标,缺口应较少
    assert isinstance(result.gaps, list)


def test_heuristic_gap_analysis_empty_session():
    """空会话(无材料)应报高优先级缺口。"""
    session = evidence_chain.create_session(
        title="空会话", experiment_type="data_model", claim_texts=[CLAIM]
    )
    result = agent_service.analyze_gaps(session.session_id)

    high_gaps = [g for g in result.gaps if g["priority"] == "high"]
    gap_names = " ".join(g["missing"] for g in result.gaps)
    assert "实验计划" in gap_names, "应报缺计划材料"
    assert "执行" in gap_names, "应报缺执行材料"
    assert len(high_gaps) >= 2, "缺计划和执行应都是高优先级"


def _setup_for_followups():
    """创建缺基线/重复证据的会话(产生 insufficient 发现)。"""
    session = evidence_chain.create_session(
        title="追问测试", experiment_type="data_model", claim_texts=[CLAIM]
    )
    # 计划只提划分和指标,缺基线和重复运行说明
    evidence_chain.extract_from_text(
        session.session_id,
        "实验计划:数据按设备划分,训练集与测试集设备编号不重叠。指标 F1。",
        "plan.md",
        "plan",
    )
    evidence_chain.extract_from_text(
        session.session_id,
        "from sklearn.model_selection import train_test_split\n"
        "X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2)\n",
        "train.py",
        "execution",
    )
    store = data_store.require(session.session_id)
    for f in store.facts_for_session():
        if f.status.value == "pending_user_confirm":
            evidence_chain.confirm_fact(session.session_id, f.fact_id, "confirm")
    return session.session_id


def test_heuristic_followups():
    """启发式追问:信息不足的发现应生成追问。"""
    session_id = _setup_for_followups()
    review_service.run_review(session_id)
    report = data_store.require(session_id).latest_report()
    insufficient = [f for f in report.findings if f.level.value == "insufficient"]
    assert len(insufficient) >= 2, f"缺基线+重复应产生至少2个 insufficient 发现,实际:{len(insufficient)}"

    followups = agent_service.generate_followups(session_id)
    assert len(followups) > 0, "有信息不足发现时应生成追问"
    for f in followups:
        assert f.question, "追问不能为空"
        assert f.what_to_provide, "追问应说明要提供什么"
    # 追问内容应覆盖基线和重复运行
    all_text = " ".join(f.what_to_provide for f in followups)
    assert "基线" in all_text, f"追问应覆盖基线缺口,实际:{all_text}"
    assert "重复" in all_text or "标准差" in all_text, f"追问应覆盖重复运行缺口,实际:{all_text}"


def test_deep_review_no_llm_returns_empty():
    """无模型时,模型复核返回空(不报错)。"""
    session_id = _setup_with_materials()
    review_service.run_review(session_id)
    result = agent_service.deep_review(session_id)
    assert result == [], "无模型时模型复核应返回空列表"


def test_preset_teaching_case():
    """预设教学案例:根据触发规则选案例,参考答案非空。"""
    session_id = _setup_with_materials()
    review_service.run_review(session_id)
    case = agent_service.generate_teaching_case(session_id)

    assert case.source == "preset"
    assert case.case_description, "案例描述不能为空"
    assert case.question, "思考问题不能为空"
    assert case.reference_answer, "参考答案不能为空"
    assert case.hint, "提示不能为空"
    # 触发了泛化规则,应选泛化相关案例
    assert "划分" in case.reference_answer or "泄漏" in case.reference_answer, (
        f"应选划分/泄漏相关案例,实际参考答案:{case.reference_answer[:50]}"
    )


def test_agent_does_not_crash_on_fresh_session():
    """全新会话(无报告)调用智能体不崩溃。"""
    session = evidence_chain.create_session(
        title="全新", experiment_type="data_model", claim_texts=[CLAIM]
    )
    # 方向审查应正常
    d = agent_service.analyze_direction(session.session_id)
    assert d is not None
    # 缺口分析应正常
    g = agent_service.analyze_gaps(session.session_id)
    assert g is not None
    # 无报告时追问应返回空(不崩溃)
    f = agent_service.generate_followups(session.session_id)
    assert f == []
    # 教学案例应正常(预设库兜底)
    c = agent_service.generate_teaching_case(session.session_id)
    assert c.case_description


if __name__ == "__main__":
    test_llm_unavailable_uses_heuristic()
    test_heuristic_direction_analysis()
    test_heuristic_gap_analysis()
    test_heuristic_gap_analysis_empty_session()
    test_heuristic_followups()
    test_deep_review_no_llm_returns_empty()
    test_preset_teaching_case()
    test_agent_does_not_crash_on_fresh_session()
    print("智能体降级模式测试全部通过")