"""主张—证据图测试:拆解、连边、反证检查、用户校准、评估指标。

评估指标(对应 P0 需求"用标注样本评估"):
1. 支持边准确率:标记为 SUPPORTS 的边是否确实应当支持(用标注样本核对)
2. 漏掉反证率:存在反证的场景是否被 counter_exists 捕获,而非漏判
3. 引用覆盖率:规则边绑定的 fact_id 是否全部指向已确认且锚点已验证的事实

运行:cd backend && python -m pytest tests/test_claim_graph.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.claim_graph import (
    CounterProofStatus,
    EdgeRelation,
    EdgeStatus,
    EvidenceDirection,
    TestAspect,
)
from app.models.evidence import FactStatus
from app.services import claim_graph_service, data_store, evidence_chain


CLAIM = "模型 A 比基线 B 更能预测新设备的故障,且更稳定。"

PLAN_GOOD = (
    "实验计划:\n"
    "1. 数据按设备划分,训练集与测试集设备不重叠。\n"
    "2. 评价指标为 F1 和 AUC。\n"
    "3. 基线为逻辑回归。\n"
    "4. 重复运行 5 次,报告均值±标准差。\n"
)

EXEC_LEAKY = (
    "model_train.py\n"
    "from sklearn.model_selection import train_test_split\n"
    "X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)\n"
    "model.fit(X_train, y_train)\n"
    "print('F1:', f1_score(y_test, model.predict(X_test)))\n"
)

EXEC_GOOD = (
    "model_train.py\n"
    "from sklearn.model_selection import GroupShuffleSplit\n"
    "split = GroupShuffleSplit(n_splits=5, test_size=0.2, random_state=42)\n"
    "for train_idx, test_idx in split.split(X, y, groups=device_ids):\n"
    "    model.fit(X[train_idx], y[train_idx])\n"
    "print('F1 mean±std: 0.85±0.02')\n"
)

RESULT_WITH_BASELINE = (
    "results.csv\n"
    "method,F1,AUC\n"
    "model_A,0.85,0.91\n"
    "baseline_B,0.72,0.78\n"
)


def _new_session(claim: str = CLAIM):
    return evidence_chain.create_session(
        title="图测试", experiment_type="data_model", claim_texts=[claim]
    )


def _ingest(session_id: str, text: str, filename: str, role: str):
    return evidence_chain.extract_from_text(session_id, text, filename, role)


def _confirm_all(session_id: str):
    store = data_store.require(session_id)
    for f in list(store.facts.values()):
        if f.status == FactStatus.PENDING:
            evidence_chain.confirm_fact(session_id, f.fact_id, "confirm")


# ---- 基础功能 ----


def test_decompose_claim_into_sub_claims():
    """主张应拆出 scope/comparison/stability/baseline_fairness/metric_avail 子主张。"""
    session = _new_session()
    graph = claim_graph_service.build_graph(session.session_id)
    aspects = {sc.test_aspect for sc in graph.sub_claims}
    assert TestAspect.SCOPE in aspects, "含'新设备'应拆出 scope 子主张"
    assert TestAspect.COMPARISON in aspects, "含'比'应拆出 comparison 子主张"
    assert TestAspect.STABILITY in aspects, "含'更稳定'应拆出 stability 子主张"
    assert TestAspect.BASELINE_FAIRNESS in aspects, "比较主张应拆出 baseline_fairness"
    assert TestAspect.METRIC_AVAIL in aspects, "所有主张都应有 metric_avail"


def test_empty_facts_yield_missing_premise_edges():
    """无已确认事实时,所有边应为 UNKNOWN + missing_premise。"""
    session = _new_session()
    graph = claim_graph_service.build_graph(session.session_id)
    assert graph.active_edge_count() > 0
    for e in graph.edges:
        if not e.is_active():
            continue
        assert e.relation == EdgeRelation.UNKNOWN, f"无事实时边应为 UNKNOWN,得到 {e.relation}"
        assert e.direction == EvidenceDirection.MISSING_PREMISE
        assert e.fact_id is None


def test_leaky_execution_builds_contradicts_edge():
    """执行为记录级划分时,scope 子主张应有 CONTRADICTS 边 + counter_exists。"""
    session = _new_session()
    _ingest(session.session_id, PLAN_GOOD, "plan.md", "plan")
    _ingest(session.session_id, EXEC_LEAKY, "leak.py", "execution")
    _confirm_all(session.session_id)

    graph = claim_graph_service.build_graph(session.session_id)
    scope_sc = next(sc for sc in graph.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    scope_edges = graph.edges_for_sub_claim(scope_sc.sub_claim_id)

    relations = [e.effective_relation() for e in scope_edges]
    assert EdgeRelation.CONTRADICTS in relations, (
        f"泄漏场景 scope 边应含 CONTRADICTS,得到 {relations}"
    )

    check = graph.counter_check_for_sub_claim(scope_sc.sub_claim_id)
    assert check is not None
    assert check.proof_status == CounterProofStatus.COUNTER_EXISTS, (
        f"记录级划分应判定 counter_exists,得到 {check.proof_status}"
    )


def test_good_execution_builds_supports_edge():
    """执行为组级划分时,scope 子主张应有 SUPPORTS 边。"""
    session = _new_session()
    _ingest(session.session_id, PLAN_GOOD, "plan.md", "plan")
    _ingest(session.session_id, EXEC_GOOD, "good.py", "execution")
    _confirm_all(session.session_id)

    graph = claim_graph_service.build_graph(session.session_id)
    scope_sc = next(sc for sc in graph.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    scope_edges = graph.edges_for_sub_claim(scope_sc.sub_claim_id)
    relations = [e.effective_relation() for e in scope_edges]
    assert EdgeRelation.SUPPORTS in relations, f"组级划分 scope 边应含 SUPPORTS,得到 {relations}"


# ---- 评估指标 1:支持边准确率 ----


def test_support_edge_accuracy_on_annotated_samples():
    """标注样本评估:标记为 SUPPORTS 的边是否确实应当支持。

    样本 1(泄漏):scope 边不应有 SUPPORTS(执行为记录级划分)
    样本 2(良好):scope 边应有 SUPPORTS(执行为组级划分)
    """
    # 样本 1:泄漏场景
    s1 = _new_session()
    _ingest(s1.session_id, PLAN_GOOD, "plan.md", "plan")
    _ingest(s1.session_id, EXEC_LEAKY, "leak.py", "execution")
    _confirm_all(s1.session_id)
    g1 = claim_graph_service.build_graph(s1.session_id)

    scope1 = next(sc for sc in g1.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    s1_scope_edges = g1.edges_for_sub_claim(scope1.sub_claim_id)
    # 标注:泄漏场景下执行侧不应有 SUPPORTS 边
    exec_supports = [
        e for e in s1_scope_edges
        if e.effective_relation() == EdgeRelation.SUPPORTS
        and e.direction == EvidenceDirection.EXECUTION
    ]
    assert len(exec_supports) == 0, (
        f"泄漏场景执行侧不应有 SUPPORTS 边(支持边准确率违规),得到 {len(exec_supports)} 条"
    )

    # 样本 2:良好场景
    s2 = _new_session()
    _ingest(s2.session_id, PLAN_GOOD, "plan.md", "plan")
    _ingest(s2.session_id, EXEC_GOOD, "good.py", "execution")
    _ingest(s2.session_id, RESULT_WITH_BASELINE, "results.csv", "execution")
    _confirm_all(s2.session_id)
    g2 = claim_graph_service.build_graph(s2.session_id)

    scope2 = next(sc for sc in g2.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    s2_scope_edges = g2.edges_for_sub_claim(scope2.sub_claim_id)
    exec_supports2 = [
        e for e in s2_scope_edges
        if e.effective_relation() == EdgeRelation.SUPPORTS
        and e.direction == EvidenceDirection.EXECUTION
    ]
    assert len(exec_supports2) > 0, "良好场景执行侧应有 SUPPORTS 边"


# ---- 评估指标 2:漏掉反证率 ----


def test_missed_counter_evidence_rate():
    """标注样本评估:存在反证的场景是否被 counter_exists 捕获。

    反证场景 A:执行为记录级划分(泄漏反证)
    反证场景 B:稳定性主张但仅单次运行(偶然性反证)
    无反证场景 C:提供了无交集直接证据(反证被排除)
    """
    # 场景 A:泄漏
    sa = _new_session()
    _ingest(sa.session_id, PLAN_GOOD, "plan.md", "plan")
    _ingest(sa.session_id, EXEC_LEAKY, "leak.py", "execution")
    _confirm_all(sa.session_id)
    ga = claim_graph_service.build_graph(sa.session_id)
    scope_a = next(sc for sc in ga.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    check_a = ga.counter_check_for_sub_claim(scope_a.sub_claim_id)
    assert check_a.proof_status == CounterProofStatus.COUNTER_EXISTS, (
        f"泄漏场景不应漏掉反证,得到 {check_a.proof_status}"
    )

    # 场景 B:仅单次运行(稳定性反证)
    sb = _new_session()
    _ingest(sb.session_id, EXEC_LEAKY, "leak.py", "execution")
    _confirm_all(sb.session_id)
    gb = claim_graph_service.build_graph(sb.session_id)
    stab_b = next(
        (sc for sc in gb.sub_claims if sc.test_aspect == TestAspect.STABILITY), None
    )
    if stab_b:
        check_b = gb.counter_check_for_sub_claim(stab_b.sub_claim_id)
        assert check_b is not None
        # 无重复运行信息:应为 no_counter_found 或 counter_exists,不能是 counter_refuted
        assert check_b.proof_status != CounterProofStatus.COUNTER_REFUTED, (
            "无多次运行数据时,偶然性反证不应被判为已排除"
        )

    # 场景 C:良好场景 + 无交集证据
    sc_session = _new_session()
    _ingest(sc_session.session_id, PLAN_GOOD, "plan.md", "plan")
    _ingest(sc_session.session_id, EXEC_GOOD, "good.py", "execution")
    _confirm_all(sc_session.session_id)
    gc = claim_graph_service.build_graph(sc_session.session_id)
    scope_c = next(sc for sc in gc.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    check_c = gc.counter_check_for_sub_claim(scope_c.sub_claim_id)
    # 计划中有"设备不重叠"直接证据:应为 counter_refuted 或 no_counter_found(不能是 counter_exists)
    assert check_c.proof_status != CounterProofStatus.COUNTER_EXISTS, (
        f"有无交集证据时不应判 counter_exists,得到 {check_c.proof_status}"
    )


# ---- 评估指标 3:引用覆盖率 ----


def test_citation_coverage_all_edges_bind_verified_anchors():
    """规则边绑定的 fact_id 必须全部指向已确认且锚点已验证的事实(100% 覆盖)。"""
    session = _new_session()
    _ingest(session.session_id, PLAN_GOOD, "plan.md", "plan")
    _ingest(session.session_id, EXEC_GOOD, "good.py", "execution")
    _ingest(session.session_id, RESULT_WITH_BASELINE, "results.csv", "execution")
    _confirm_all(session.session_id)

    graph = claim_graph_service.build_graph(session.session_id)
    store = data_store.require(session.session_id)

    bound_edges = [e for e in graph.edges if e.fact_id is not None and e.is_active()]
    assert len(bound_edges) > 0, "良好场景应有绑定事实的边"

    for e in bound_edges:
        fact = store.facts.get(e.fact_id)
        assert fact is not None, f"边 {e.edge_id} 引用了不存在的事实 {e.fact_id}"
        assert fact.is_usable(), (
            f"边 {e.edge_id} 引用了未确认事实 {e.fact_id}(status={fact.status})"
        )
        doc = store.docs.get(fact.source.material_id)
        assert doc is not None, f"事实 {e.fact_id} 的源文档不存在"
        assert fact.source.verify(doc), (
            f"边 {e.edge_id} 引用的事实 {e.fact_id} 锚点校验失败(幻觉)"
        )


# ---- 用户校准 ----


def test_user_can_correct_and_reject_edges():
    """用户可纠正边的关系类型,也可拒绝边。"""
    session = _new_session()
    _ingest(session.session_id, PLAN_GOOD, "plan.md", "plan")
    _ingest(session.session_id, EXEC_LEAKY, "leak.py", "execution")
    _confirm_all(session.session_id)
    graph = claim_graph_service.build_graph(session.session_id)

    scope_sc = next(sc for sc in graph.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    edge = next(
        e for e in graph.edges_for_sub_claim(scope_sc.sub_claim_id)
        if e.effective_relation() == EdgeRelation.CONTRADICTS
    )

    # 纠正:用户认为这条边其实是 supports
    corrected = claim_graph_service.confirm_edge(
        session.session_id, edge.edge_id, "correct", "supports"
    )
    assert corrected.status == EdgeStatus.CORRECTED
    assert corrected.effective_relation() == EdgeRelation.SUPPORTS

    # 拒绝另一条边
    other = next(
        (e for e in graph.edges_for_sub_claim(scope_sc.sub_claim_id)
         if e.edge_id != edge.edge_id and e.is_active()),
        None,
    )
    if other:
        rejected = claim_graph_service.confirm_edge(
            session.session_id, other.edge_id, "reject"
        )
        assert rejected.status == EdgeStatus.REJECTED
        assert not rejected.is_active()


def test_calibration_preserved_on_rebuild():
    """重建图后,用户对边的纠正/拒绝应被保留。"""
    session = _new_session()
    _ingest(session.session_id, PLAN_GOOD, "plan.md", "plan")
    _ingest(session.session_id, EXEC_LEAKY, "leak.py", "execution")
    _confirm_all(session.session_id)
    graph = claim_graph_service.build_graph(session.session_id)

    scope_sc = next(sc for sc in graph.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    edge = next(
        e for e in graph.edges_for_sub_claim(scope_sc.sub_claim_id)
        if e.effective_relation() == EdgeRelation.CONTRADICTS
    )
    claim_graph_service.confirm_edge(session.session_id, edge.edge_id, "reject")

    # 重建(模拟用户又确认了新事实后重新构建)
    graph2 = claim_graph_service.build_graph(session.session_id)
    scope2 = next(sc for sc in graph2.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    matched = [
        e for e in graph2.edges
        if e.sub_claim_id == scope2.sub_claim_id
        and e.fact_id == edge.fact_id
        and e.status == EdgeStatus.REJECTED
    ]
    assert len(matched) == 1, "重建后用户的拒绝校准应被保留"


def test_counter_check_distinguishes_not_found_vs_refuted():
    """核心认识论区分:'没找到反证' ≠ '证明不存在反证'。"""
    # 无交集证据 → counter_refuted
    s1 = _new_session()
    _ingest(s1.session_id, PLAN_GOOD, "plan.md", "plan")  # 含"设备不重叠"
    _ingest(s1.session_id, EXEC_GOOD, "good.py", "execution")
    _confirm_all(s1.session_id)
    g1 = claim_graph_service.build_graph(s1.session_id)
    scope1 = next(sc for sc in g1.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    check1 = g1.counter_check_for_sub_claim(scope1.sub_claim_id)
    assert check1.proof_status == CounterProofStatus.COUNTER_REFUTED, (
        f"有无交集直接证据应判 counter_refuted,得到 {check1.proof_status}"
    )
    assert len(check1.missing_to_prove_absence) == 0

    # 无直接证据 → no_counter_found
    s2 = _new_session()
    _ingest(s2.session_id, EXEC_GOOD, "good.py", "execution")  # 组级划分但无交集证据
    _confirm_all(s2.session_id)
    g2 = claim_graph_service.build_graph(s2.session_id)
    scope2 = next(sc for sc in g2.sub_claims if sc.test_aspect == TestAspect.SCOPE)
    check2 = g2.counter_check_for_sub_claim(scope2.sub_claim_id)
    assert check2.proof_status == CounterProofStatus.NO_COUNTER_FOUND, (
        f"无交集直接证据应判 no_counter_found,得到 {check2.proof_status}"
    )
    assert len(check2.missing_to_prove_absence) > 0, (
        "no_counter_found 必须告知用户还需要什么证据才能升级为 counter_refuted"
    )