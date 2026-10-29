"""审查规则测试:有漏洞 / 无漏洞 / 证据不足 三类案例,测漏报与误报。

运行:cd backend && python -m pytest tests/test_review_rules.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.review import FindingLevel
from app.services import data_store, evidence_chain, review_service


CLAIM = "模型 A 比基线 B 更能预测新设备的故障,且更稳定。"


def _setup(claim: str = CLAIM):
    session = evidence_chain.create_session(
        title="规则测试", experiment_type="data_model", claim_texts=[claim]
    )
    return session


def _confirm_all(session_id: str):
    store = data_store.require(session_id)
    for f in store.facts_for_session():
        if f.status.value == "pending_user_confirm":
            evidence_chain.confirm_fact(session_id, f.fact_id, "confirm")


# ---------- 案例1:有漏洞(应检出,测漏报) ----------

def test_flawed_case_split_contradiction():
    """计划写按设备划分,执行用 train_test_split(记录级随机),
    主张预测新设备 -> 应触发明确矛盾(数据泄漏)。"""
    session = _setup()
    evidence_chain.extract_from_text(
        session.session_id,
        "实验计划:数据按设备划分,训练集与测试集设备编号不重叠。",
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
    _confirm_all(session.session_id)
    report = review_service.run_review(session.session_id)

    levels = {f.rule_id: f.level for f in report.findings}
    assert levels.get("dm_split_consistency") == FindingLevel.CONTRADICTION, (
        f"划分不一致应触发明确矛盾,实际:{levels}"
    )
    assert levels.get("dm_claim_generalization") == FindingLevel.CONTRADICTION, (
        f"新设备主张+记录级划分应触发泄漏矛盾,实际:{levels}"
    )
    # 每条发现的证据必须可回溯
    for f in report.findings:
        if f.evidence:
            store = data_store.require(session.session_id)
            for ref in f.evidence:
                doc = store.docs[ref.source.material_id]
                assert ref.source.verify(doc), f"发现 {f.finding_id} 的证据锚点校验失败"


def test_flawed_case_stability_single_run():
    """主张更稳定,但只有 random_state 无多次运行 -> 应触发潜在风险。"""
    session = _setup()
    evidence_chain.extract_from_text(
        session.session_id,
        "X_tr, X_te = train_test_split(X, y, random_state=42)\n",
        "train.py",
        "execution",
    )
    _confirm_all(session.session_id)
    report = review_service.run_review(session.session_id)
    levels = {f.rule_id: f.level for f in report.findings}
    assert levels.get("dm_repetition") == FindingLevel.RISK, (
        f"稳定性主张+仅种子应触发风险,实际:{levels}"
    )


# ---------- 案例2:无漏洞(不应误报) ----------

def test_clean_case_no_false_positive():
    """计划与执行均为按设备划分,有多次运行波动,有基线,有指标
    -> 不应触发矛盾;最多只有"设备编号交集待补"的风险提示。"""
    session = _setup()
    evidence_chain.extract_from_text(
        session.session_id,
        "实验计划:\n"
        "1. 数据按设备划分,测试集为未见设备。\n"
        "2. 基线为逻辑回归,相同划分与指标下评估。\n"
        "3. 重复运行 5 次,报告均值±标准差。\n",
        "plan.md",
        "plan",
    )
    evidence_chain.extract_from_text(
        session.session_id,
        "from sklearn.model_selection import GroupShuffleSplit\n"
        "gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)\n"
        "for tr, te in gss.split(X, y, groups=device_ids):\n"
        "    pass\n"
        "# 结果: F1 = 0.87 ± 0.02 (5 runs)\n",
        "train.py",
        "execution",
    )
    _confirm_all(session.session_id)
    report = review_service.run_review(session.session_id)

    levels = {f.rule_id: f.level for f in report.findings}
    # 不应有任何明确矛盾(误报检测)
    contradictions = [r for r, lv in levels.items() if lv == FindingLevel.CONTRADICTION]
    assert not contradictions, f"无漏洞案例不应触发矛盾,误报:{contradictions}"
    # 稳定性规则不应触发(有多轮数据)
    assert "dm_repetition" not in levels, "有均值±标准差时不应触发稳定性风险"
    # 基线规则不应触发
    assert "dm_baseline" not in levels, "有基线记录时不应触发基线不足"
    # 指标规则不应触发
    assert "dm_metric" not in levels, "有指标时不应触发指标不足"


# ---------- 案例3:证据不足(应标为信息不足,而非妄下结论) ----------

def test_insufficient_case_no_baseline():
    """主张比较关系但无基线材料 -> 应标信息不足,不得下矛盾结论。"""
    session = _setup()
    evidence_chain.extract_from_text(
        session.session_id,
        "数据按设备划分。评价指标为 F1。",
        "plan.md",
        "plan",
    )
    _confirm_all(session.session_id)
    report = review_service.run_review(session.session_id)
    levels = {f.rule_id: f.level for f in report.findings}
    assert levels.get("dm_baseline") == FindingLevel.INSUFFICIENT, (
        f"无基线应标信息不足,实际:{levels}"
    )


def test_insufficient_case_only_plan_no_execution():
    """只提供计划、无执行材料 -> 划分一致性应标信息不足。"""
    session = _setup()
    evidence_chain.extract_from_text(
        session.session_id,
        "实验计划:数据按设备划分,指标 F1,基线逻辑回归,重复 5 次报告均值±标准差。",
        "plan.md",
        "plan",
    )
    _confirm_all(session.session_id)
    report = review_service.run_review(session.session_id)
    levels = {f.rule_id: f.level for f in report.findings}
    assert levels.get("dm_split_consistency") == FindingLevel.INSUFFICIENT, (
        f"缺执行侧应标信息不足,实际:{levels}"
    )


# ---------- 复查测试 ----------

def test_recheck_resolves_contradiction():
    """修改执行代码为按设备划分后复查,原矛盾应解除。"""
    from app.services import recheck_service

    session = _setup()
    # 初版:有漏洞
    evidence_chain.extract_from_text(
        session.session_id,
        "实验计划:数据按设备划分。",
        "plan.md",
        "plan",
    )
    evidence_chain.extract_from_text(
        session.session_id,
        "X_tr, X_te = train_test_split(X, y, test_size=0.2)\n",
        "train.py",
        "execution",
    )
    _confirm_all(session.session_id)
    old_report = review_service.run_review(session.session_id)
    old_levels = {f.rule_id: f.level for f in old_report.findings}
    assert old_levels.get("dm_split_consistency") == FindingLevel.CONTRADICTION

    # 修改:补充正确执行代码
    evidence_chain.extract_from_text(
        session.session_id,
        "from sklearn.model_selection import GroupShuffleSplit\n"
        "gss = GroupShuffleSplit(n_splits=1, test_size=0.2)\n"
        "for tr, te in gss.split(X, y, groups=device_ids):\n"
        "    pass\n",
        "train_v2.py",
        "execution",
    )
    # 确认新事实
    store = data_store.require(session.session_id)
    for f in store.facts_for_session():
        if f.status.value == "pending_user_confirm":
            evidence_chain.confirm_fact(session.session_id, f.fact_id, "confirm")
    # 拒绝旧的记录级划分事实(已废弃)
    for f in store.facts_for_session():
        if "train_test_split" in f.effective_value() and f.is_usable():
            evidence_chain.confirm_fact(session.session_id, f.fact_id, "reject")

    result = recheck_service.run_recheck(session.session_id, "已改为按设备划分")
    by_rule = {c.rule_id: c for c in result.comparisons}
    assert by_rule["dm_split_consistency"].resolved, "修改后划分矛盾应解除"


# ---------- 算法与系统性能实验规则测试 ----------

AS_CLAIM = "新算法 A 比基线 B 更快,且更稳定。"


def _setup_as(claim: str = AS_CLAIM):
    session = evidence_chain.create_session(
        title="算法实验测试", experiment_type="algorithm_system", claim_texts=[claim]
    )
    return session


def test_as_baseline_missing_insufficient():
    """算法实验:主张含比较但无基线信息 -> 信息不足。"""
    session = _setup_as()
    evidence_chain.extract_from_text(
        session.session_id,
        "实验计划:测试算法 A 的延迟与吞吐。评价指标 latency、throughput。",
        "plan.md",
        "plan",
    )
    _confirm_all(session.session_id)
    report = review_service.run_review(session.session_id)
    levels = {f.rule_id: f.level for f in report.findings}
    assert levels.get("as_baseline_check") == FindingLevel.INSUFFICIENT, (
        f"缺基线应标信息不足,实际:{levels}"
    )


def test_as_stability_seed_only_risk():
    """算法实验:主张'更稳定'但只有随机种子(单次运行)-> 潜在风险。"""
    session = _setup_as()
    evidence_chain.extract_from_text(
        session.session_id,
        "实验计划:对比算法 A 与基线 B,指标 latency,基线 B 为 FIFO。",
        "plan.md",
        "plan",
    )
    evidence_chain.extract_from_text(
        session.session_id,
        "np.random.seed(42)\nlatency_a = 12.3\nlatency_b = 15.6\n",
        "bench.py",
        "execution",
    )
    _confirm_all(session.session_id)
    report = review_service.run_review(session.session_id)
    levels = {f.rule_id: f.level for f in report.findings}
    assert levels.get("as_stability_repetition") == FindingLevel.RISK, (
        f"只有种子无多次运行应标风险,实际:{levels}"
    )


def test_as_clean_case_no_false_positive():
    """算法实验:计划+执行+基线+指标+多次运行齐全 -> 稳定性规则不误报。"""
    session = _setup_as()
    evidence_chain.extract_from_text(
        session.session_id,
        "实验计划:对比算法 A 与基线 B(FIFO),指标 latency、throughput,重复 5 次报告均值±标准差。",
        "plan.md",
        "plan",
    )
    evidence_chain.extract_from_text(
        session.session_id,
        "baseline = FIFO()\n"
        "latency_a = 12.3 ± 0.8\nlatency_b = 15.6 ± 1.2\n"
        "n_runs = 5\n",
        "bench.py",
        "execution",
    )
    _confirm_all(session.session_id)
    report = review_service.run_review(session.session_id)
    levels = {f.rule_id: f.level for f in report.findings}
    assert "as_stability_repetition" not in levels, (
        f"多次运行证据齐全时稳定性规则不应触发,实际:{levels}"
    )
    assert "as_plan_exec_coverage" not in levels, "计划+执行齐全时覆盖规则不应触发"


def test_as_no_materials_coverage_insufficient():
    """算法实验:无任何材料 -> 覆盖规则报信息不足(不再产出空报告)。"""
    session = _setup_as()
    report = review_service.run_review(session.session_id)
    rule_ids = {f.rule_id for f in report.findings}
    assert "as_plan_exec_coverage" in rule_ids, (
        f"无材料时应触发覆盖规则,实际:{rule_ids}"
    )
    assert len(report.findings) > 0, "algorithm_system 不应产出空报告"


if __name__ == "__main__":
    test_flawed_case_split_contradiction()
    test_flawed_case_stability_single_run()
    test_clean_case_no_false_positive()
    test_insufficient_case_no_baseline()
    test_insufficient_case_only_plan_no_execution()
    test_recheck_resolves_contradiction()
    test_as_baseline_missing_insufficient()
    test_as_stability_seed_only_risk()
    test_as_clean_case_no_false_positive()
    test_as_no_materials_coverage_insufficient()
    print("审查规则测试全部通过(漏报与误报检测通过)")