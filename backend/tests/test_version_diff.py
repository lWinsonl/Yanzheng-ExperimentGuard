"""版本差异复审与学习迁移评估测试(P2)。

评估指标(对应 P2 需求):
1. 稳定身份:同一问题跨报告可追踪(不只按 rule_id)
2. 五态判定:已解决/缓解/仍存在/新问题/证据不足
3. 修改理由对照:声称改动 vs 事实层面实际变化
4. 迁移题评分:看推理过程(四维评分)
5. 已解决精确率:人工标签验证

运行:cd backend && python -m pytest tests/test_version_diff.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.evidence import FactStatus
from app.models.version_diff import (
    FindingIdentity,
    RevisionAlignmentLevel,
    VersionDiffStatus,
)
from app.services import data_store, evidence_chain, review_service, version_diff_service


# ---- 稳定身份 ----

def test_identity_deterministic():
    """同一组组件 → 同一身份哈希(确定性)。"""
    id1 = FindingIdentity.compute("rule_a", ["c1", "c2"], ["data_split", "metric"], "split")
    id2 = FindingIdentity.compute("rule_a", ["c2", "c1"], ["metric", "data_split"], "split")
    assert id1.identity_hash == id2.identity_hash  # 排序后一致


def test_identity_different_claims_different_hash():
    """同一规则不同主张 → 不同身份(不只按 rule_id)。"""
    id1 = FindingIdentity.compute("rule_a", ["c1"], ["data_split"], "split")
    id2 = FindingIdentity.compute("rule_a", ["c2"], ["data_split"], "split")
    assert id1.identity_hash != id2.identity_hash


def test_identity_different_evidence_scope_different_hash():
    """同一规则同一主张但证据范围不同 → 不同身份。"""
    id1 = FindingIdentity.compute("rule_a", ["c1"], ["data_split"], "split")
    id2 = FindingIdentity.compute("rule_a", ["c1"], ["metric"], "split")
    assert id1.identity_hash != id2.identity_hash


# ---- 端到端:版本差异五态 ----

CLAIM = "模型 A 比基线 B 更能预测新设备的故障。"

PLAN_GROUP = (
    "实验计划:\n"
    "1. 数据按设备划分,训练集与测试集设备不重叠。\n"
    "2. 指标为 F1。\n"
    "3. 基线为逻辑回归。\n"
)

EXEC_LEAKY = (
    "model.py\n"
    "from sklearn.model_selection import train_test_split\n"
    "X_train, X_test = train_test_split(X, y, test_size=0.2)\n"
)

EXEC_GOOD = (
    "model.py\n"
    "from sklearn.model_selection import GroupShuffleSplit\n"
    "split = GroupShuffleSplit(n_splits=5, test_size=0.2)\n"
    "for train_idx, test_idx in split.split(X, y, groups=device_ids):\n"
    "    model.fit(X[train_idx], y[train_idx])\n"
)

RESULT_OK = "results.csv\nmethod,F1\nmodel_A,0.85\nbaseline_B,0.72\n"


def _setup_and_review(exec_text=EXEC_LEAKY):
    """创建会话、摄取材料、确认事实、运行审查。"""
    session = evidence_chain.create_session(
        title="版本差异测试", experiment_type="data_model", claim_texts=[CLAIM]
    )
    sid = session.session_id
    evidence_chain.extract_from_text(sid, PLAN_GROUP, "plan.txt", "plan")
    evidence_chain.extract_from_text(sid, exec_text, "exec.py", "execution")
    evidence_chain.extract_from_text(sid, RESULT_OK, "results.csv", "result")

    store = data_store.require(sid)
    for f in list(store.facts.values()):
        if f.status == FactStatus.PENDING:
            evidence_chain.confirm_fact(sid, f.fact_id, "confirm")
    review_service.run_review(sid)
    return sid


def _replace_exec(sid, new_exec_text):
    """替换执行材料(replace 模式)并确认新事实。"""
    evidence_chain.clear_materials(sid, "execution")
    evidence_chain.extract_from_text(sid, new_exec_text, "exec_new.py", "execution")
    store = data_store.require(sid)
    for f in list(store.facts.values()):
        if f.status == FactStatus.PENDING:
            evidence_chain.confirm_fact(sid, f.fact_id, "confirm")


def test_resolved_when_split_fixed():
    """修复划分方式后,原矛盾发现判定为已解决。"""
    sid = _setup_and_review(EXEC_LEAKY)
    # 确认有矛盾发现
    report = data_store.require(sid).latest_report()
    assert any(f.level.value == "risk" for f in report.findings)

    # 修复:替换为按设备划分
    _replace_exec(sid, EXEC_GOOD)

    # 版本差异复审
    result = version_diff_service.run_version_diff(sid, "已改为按设备划分,使用GroupShuffleSplit")
    resolved = [c for c in result.comparisons if c.status == VersionDiffStatus.RESOLVED]
    assert len(resolved) >= 1
    assert all(c.reason for c in resolved)


def test_persists_when_not_fixed():
    """未修复时,原矛盾发现判定为仍存在。"""
    sid = _setup_and_review(EXEC_LEAKY)
    # 重新运行(不修改材料)
    result = version_diff_service.run_version_diff(sid, "没有修改")
    persists = [c for c in result.comparisons if c.status == VersionDiffStatus.PERSISTS]
    assert len(persists) >= 1


def test_new_issue_detected():
    """新报告中出现旧报告没有的问题 → 新问题。"""
    sid = _setup_and_review(EXEC_GOOD)  # 无泄漏,可能无矛盾发现
    # 替换为泄漏版本
    _replace_exec(sid, EXEC_LEAKY)
    result = version_diff_service.run_version_diff(sid, "换了个划分方式")
    new_issues = [c for c in result.comparisons if c.status == VersionDiffStatus.NEW_ISSUE]
    assert len(new_issues) >= 1


def test五种状态计数正确():
    """统计:五态计数正确。"""
    sid = _setup_and_review(EXEC_LEAKY)
    version_diff_service.run_version_diff(sid, "测试")
    stats = version_diff_service.get_stats(sid)
    assert stats.total_comparisons >= 1
    # 至少有一个 resolved 或 persists
    assert stats.resolved_count + stats.persists_count + stats.mitigated_count >= 1


# ---- 修改理由对照 ----

def test_revision_alignment_aligned():
    """声称改了划分且确实改了 → aligned。"""
    sid = _setup_and_review(EXEC_LEAKY)
    _replace_exec(sid, EXEC_GOOD)
    result = version_diff_service.run_version_diff(sid, "已改为按设备划分")
    assert result.revision_alignment.alignment == RevisionAlignmentLevel.ALIGNED
    assert "data_split" in result.revision_alignment.claimed_changes[0] or \
        any("data_split" in c for c in result.revision_alignment.claimed_changes)
    assert len(result.revision_alignment.actual_changes) >= 1


def test_revision_alignment_not_aligned():
    """声称改了但事实没变 → not_aligned。"""
    sid = _setup_and_review(EXEC_LEAKY)
    # 不修改材料,但声称改了划分
    result = version_diff_service.run_version_diff(sid, "已改为按设备划分")
    assert result.revision_alignment.alignment == RevisionAlignmentLevel.NOT_ALIGNED
    assert "不一致" in result.revision_alignment.alignment_detail


def test_revision_alignment_no_note():
    """未提交修改理由 → not_aligned。"""
    sid = _setup_and_review(EXEC_LEAKY)
    result = version_diff_service.run_version_diff(sid, "")
    assert result.revision_alignment.alignment == RevisionAlignmentLevel.NOT_ALIGNED


# ---- 人工复核标签与已解决精确率 ----

def test_manual_label_and_resolved_precision():
    """人工标签验证已解决精确率。"""
    sid = _setup_and_review(EXEC_LEAKY)
    _replace_exec(sid, EXEC_GOOD)
    result = version_diff_service.run_version_diff(sid, "已改为按设备划分")

    resolved = [c for c in result.comparisons if c.status == VersionDiffStatus.RESOLVED]
    assert len(resolved) >= 1

    # 人工确认第一条 resolved 确实是 resolved
    version_diff_service.add_manual_label(
        sid, resolved[0].comparison_id, "resolved", labeled_by="tester"
    )

    stats = version_diff_service.get_stats(sid)
    assert stats.manual_labels == 1
    assert stats.resolved_precision == 1.0  # 人工确认 → 精确率 100%


def test_resolved_precision_with_wrong_label():
    """人工判定非 resolved → 精确率下降。"""
    sid = _setup_and_review(EXEC_LEAKY)
    _replace_exec(sid, EXEC_GOOD)
    result = version_diff_service.run_version_diff(sid, "已改为按设备划分")

    resolved = [c for c in result.comparisons if c.status == VersionDiffStatus.RESOLVED]
    # 人工判定其实仍存在
    version_diff_service.add_manual_label(
        sid, resolved[0].comparison_id, "persists", labeled_by="tester"
    )

    stats = version_diff_service.get_stats(sid)
    assert stats.resolved_precision == 0.0  # 人工判 persists → 精确率 0%


# ---- 迁移题(启发式评分) ----

def test_migration_question_generated():
    """迁移题生成(无模型时用预设情境)。"""
    sid = _setup_and_review(EXEC_LEAKY)
    result = version_diff_service.run_version_diff(sid, "测试")

    # 通过 agent_service 生成迁移题
    from app.agent.agent_service import agent_service
    mig = agent_service.generate_migration_question(sid)
    assert mig["status"] == "ok"
    q = mig["question"]
    assert q.scenario
    assert q.question
    assert q.reference_answer
    assert q.method_point


def test_migration_answer_scored():
    """迁移题回答评分:看推理过程(四维)。"""
    sid = _setup_and_review(EXEC_LEAKY)
    from app.agent.agent_service import agent_service
    mig = agent_service.generate_migration_question(sid)
    q = mig["question"]

    # 学生回答:有推理过程的好回答
    good_answer = (
        "小红的实验不能支持她的结论。因为她主张的是分类'新作者'的文章,"
        "但用随机划分会让同一作者的文章同时出现在训练集和测试集中,"
        "导致数据泄漏,模型可能只是记住了已知作者的写作风格。"
        "应该改为按作者ID分组划分,确保测试集只含训练时未见过的作者。"
    )
    result = agent_service.score_migration_answer(sid, q.question_id, good_answer)
    assert result["status"] == "feedback_only"
    answer = result["answer"]
    assert answer.total_score is None
    assert answer.identifies_core_issue is None
    assert answer.score_status == "feedback_only"
    assert answer.feedback
    result_bad = agent_service.score_migration_answer(sid, q.question_id, "不知道")
    assert result_bad["answer"].total_score is None


def test_migration_stats():
    """迁移统计:平均分、通过率。"""
    sid = _setup_and_review(EXEC_LEAKY)
    from app.agent.agent_service import agent_service
    mig = agent_service.generate_migration_question(sid)
    q = mig["question"]
    agent_service.score_migration_answer(sid, q.question_id, "这个实验有问题,因为数据泄漏,应该改划分方式")

    stats = version_diff_service.get_stats(sid)
    assert stats.migration_total == 0
    assert stats.migration_avg_score == 0


# ---- 数据一致性 ----

def test_materials_replace_clears_version_diff():
    """材料替换(数据一致性):旧版本差异数据引用的事实已不存在,应同步清除。"""
    sid = _setup_and_review(EXEC_LEAKY)
    version_diff_service.run_version_diff(sid, "测试")
    assert len(data_store.require(sid).version_diffs) == 1

    # 替换材料
    evidence_chain.clear_materials(sid, "execution")

    store = data_store.require(sid)
    assert store.version_diffs == []
    assert store.migration_questions == []
    assert store.migration_answers == []
    assert store.manual_labels == []