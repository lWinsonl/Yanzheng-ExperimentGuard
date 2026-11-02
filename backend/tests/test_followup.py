"""主动追问测试:EIV 评分排序、回答追踪、统计指标。

评估指标(对应 P1 需求):
1. 评分排序正确性:高 EIV 追问排在前面,rank 连续递增
2. 可解释性:每条追问有 score_explanation 说明"为何先问这个"
3. 回答追踪:回答后记录是否实际改变了发现(answer_changed_finding)
4. 统计指标:完成率/变化率/平均追问数可计算

运行:cd backend && python -m pytest tests/test_followup.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.followup import (
    AnswerCost,
    EvidenceType,
    FollowupQuestion,
    FollowupStatus,
)
from app.models.review import FindingLevel
from app.services import data_store, evidence_chain, followup_service, review_service


def _make_question(
    qid: str,
    severity: float,
    uncertainty: float,
    change_prob: float,
    cost: AnswerCost,
) -> FollowupQuestion:
    return FollowupQuestion(
        session_id="test-session",
        question_id=qid,
        target_finding_id="",
        sub_claim_id="",
        question=f"问题 {qid}",
        evidence_type=EvidenceType.EXPLANATION,
        evidence_format="文字说明",
        severity_score=severity,
        uncertainty=uncertainty,
        change_probability=change_prob,
        cost_factor={AnswerCost.LOW: 1.0, AnswerCost.MEDIUM: 2.0, AnswerCost.HIGH: 3.0}[cost],
    )


# ---- 评分与排序 ----

def test_eiv_score_calculation():
    """EIV = severity × uncertainty × change_probability / cost。"""
    q = _make_question("q1", 3.0, 0.8, 0.9, AnswerCost.LOW)
    followup_service.score_and_rank([q])
    assert abs(q.eiv_score - (3.0 * 0.8 * 0.9 / 1.0)) < 0.001


def test_rank_ordering():
    """高 EIV 追问排在前面,rank 从 1 开始连续递增。"""
    q_low = _make_question("low", 1.0, 0.3, 0.2, AnswerCost.HIGH)     # EIV=0.02
    q_high = _make_question("high", 3.0, 0.9, 0.9, AnswerCost.LOW)    # EIV=2.43
    q_mid = _make_question("mid", 2.0, 0.5, 0.5, AnswerCost.MEDIUM)   # EIV=0.25

    ranked = followup_service.score_and_rank([q_low, q_mid, q_high])
    assert [q.question_id for q in ranked] == ["high", "mid", "low"]
    assert [q.rank for q in ranked] == [1, 2, 3]


def test_cost_factor_penalizes_expensive_questions():
    """同等信息价值下,回答成本高的追问排后面。"""
    q_cheap = _make_question("cheap", 2.0, 0.6, 0.6, AnswerCost.LOW)    # EIV=0.72
    q_pricey = _make_question("pricey", 2.0, 0.6, 0.6, AnswerCost.HIGH)  # EIV=0.24

    ranked = followup_service.score_and_rank([q_pricey, q_cheap])
    assert ranked[0].question_id == "cheap"
    assert ranked[0].eiv_score > ranked[1].eiv_score


def test_score_explanation_generated():
    """每条追问有可解释说明,包含 EIV 数值和因子分解。"""
    q = _make_question("q1", 2.0, 0.5, 0.6, AnswerCost.MEDIUM)
    followup_service.score_and_rank([q])
    assert "EIV" in q.score_explanation
    assert "严重度" in q.score_explanation
    assert "不确定性" in q.score_explanation
    assert "可改变概率" in q.score_explanation
    assert "成本" in q.score_explanation


def test_severity_inferred_from_finding_level():
    """追问未设置严重度时,从目标发现级别推断。"""
    q = FollowupQuestion(
        session_id="s",
        question_id="q1",
        question="测试问题",
        severity_score=0,  # 未设置
        uncertainty=0.5,
        change_probability=0.5,
        cost_factor=2.0,
    )
    levels = {"find-1": "contradiction"}
    q.target_finding_id = "find-1"
    followup_service.score_and_rank([q], levels)
    assert q.severity_score == 3.0  # contradiction → 3


# ---- 端到端:生成 → 回答 → 追踪 ----

CLAIM = "模型 A 比基线 B 更能预测新设备的故障。"

PLAN_OK = (
    "实验计划:\n"
    "1. 数据按设备划分。\n"
    "2. 指标为 F1。\n"
)

EXEC_LEAKY = (
    "model.py\n"
    "from sklearn.model_selection import train_test_split\n"
    "X_train, X_test = train_test_split(X, y, test_size=0.2)\n"
)

RESULT_OK = "results.csv\nmethod,F1\nmodel_A,0.85\nbaseline_B,0.72\n"


def _setup_session_with_findings():
    """创建会话并运行审查,产生至少一条发现。"""
    from app.models.evidence import FactStatus

    session = evidence_chain.create_session(
        title="追问测试", experiment_type="data_model", claim_texts=[CLAIM]
    )
    sid = session.session_id
    evidence_chain.extract_from_text(sid, PLAN_OK, "plan.txt", "plan")
    evidence_chain.extract_from_text(sid, EXEC_LEAKY, "exec.py", "execution")
    evidence_chain.extract_from_text(sid, RESULT_OK, "results.csv", "result")

    store = data_store.require(sid)
    for f in list(store.facts.values()):
        if f.status == FactStatus.PENDING:
            evidence_chain.confirm_fact(sid, f.fact_id, "confirm")

    review_service.run_review(sid)
    return sid


def test_generate_from_findings_and_save():
    """从原始追问生成带评分的 FollowupQuestion 并保存。"""
    sid = _setup_session_with_findings()

    raw_questions = [
        {
            "question": "请提供数据划分代码片段",
            "what_to_provide": "代码",
            "why_needed": "核实是否按设备划分",
            "target_finding_id": "find-x",
            "evidence_type": "code",
            "evidence_format": "代码片段",
            "uncertainty": 0.8,
            "change_probability": 0.9,
            "answer_cost": "low",
        },
        {
            "question": "请说明基线设置",
            "what_to_provide": "说明",
            "why_needed": "核实基线公平性",
            "evidence_type": "explanation",
            "evidence_format": "文字",
            "uncertainty": 0.3,
            "change_probability": 0.2,
            "answer_cost": "high",
        },
    ]

    questions = followup_service.generate_from_findings(sid, raw_questions)
    followup_service.save_questions(sid, questions)

    assert len(questions) == 2
    # 高 EIV 排前面
    assert questions[0].rank == 1
    assert questions[0].eiv_score > questions[1].eiv_score
    # 排序正确性:划分代码追问 EIV 应高于基线说明
    assert "划分" in questions[0].question

    # 可解释性
    assert all(q.score_explanation for q in questions)

    # 证据类型绑定
    assert questions[0].evidence_type == EvidenceType.CODE

    # 持久化
    stored = followup_service.get_questions(sid)
    assert len(stored) == 2


def test_answer_tracking_changes_finding():
    """回答后重算审查,追踪发现是否变化。"""
    sid = _setup_session_with_findings()

    # 先生成并保存追问
    questions = followup_service.generate_from_findings(sid, [
        {
            "question": "请提供划分方式",
            "what_to_provide": "代码",
            "why_needed": "核实",
            "evidence_type": "code",
            "evidence_format": "代码",
            "uncertainty": 0.8,
            "change_probability": 0.9,
            "answer_cost": "low",
        },
    ])
    followup_service.save_questions(sid, questions)

    q = questions[0]
    assert q.status == FollowupStatus.PENDING

    # 回答
    answered = followup_service.record_answer(sid, q.question_id, "我用了按记录随机划分")
    assert answered.status == FollowupStatus.ANSWERED
    assert answered.answer_text == "我用了按记录随机划分"
    assert answered.answered_at != ""
    # 追踪字段已填写(无论是否改变,都必须有明确的追踪结果)
    assert isinstance(answered.answer_changed_finding, bool)
    assert answered.finding_change_detail != ""


def test_skip_question():
    """跳过追问后状态为 skipped。"""
    sid = _setup_session_with_findings()
    questions = followup_service.generate_from_findings(sid, [
        {"question": "问题1", "what_to_provide": "x", "why_needed": "y",
         "evidence_type": "explanation", "evidence_format": "文字",
         "uncertainty": 0.5, "change_probability": 0.5, "answer_cost": "medium"},
    ])
    followup_service.save_questions(sid, questions)

    skipped = followup_service.skip_question(sid, questions[0].question_id)
    assert skipped.status == FollowupStatus.SKIPPED


# ---- 统计指标 ----

def test_stats_calculation():
    """统计:完成率/变化率/平均追问数。"""
    sid = _setup_session_with_findings()
    questions = followup_service.generate_from_findings(sid, [
        {"question": "问题1", "target_finding_id": "f1",
         "what_to_provide": "x", "why_needed": "y",
         "evidence_type": "explanation", "evidence_format": "文字",
         "uncertainty": 0.5, "change_probability": 0.5, "answer_cost": "medium"},
        {"question": "问题2", "target_finding_id": "f2",
         "what_to_provide": "x", "why_needed": "y",
         "evidence_type": "explanation", "evidence_format": "文字",
         "uncertainty": 0.5, "change_probability": 0.5, "answer_cost": "medium"},
        {"question": "问题3", "target_finding_id": "f3",
         "what_to_provide": "x", "why_needed": "y",
         "evidence_type": "explanation", "evidence_format": "文字",
         "uncertainty": 0.5, "change_probability": 0.5, "answer_cost": "medium"},
    ])
    followup_service.save_questions(sid, questions)

    # 回答 2 条,跳过 1 条
    followup_service.record_answer(sid, questions[0].question_id, "回答1")
    followup_service.record_answer(sid, questions[1].question_id, "回答2")
    followup_service.skip_question(sid, questions[2].question_id)

    stats = followup_service.get_stats(sid)
    assert stats.total_questions == 3
    assert stats.answered == 2
    assert stats.skipped == 1
    assert abs(stats.completion_rate - 2 / 3) < 0.01
    # change_rate = changed / answered
    assert 0.0 <= stats.change_rate <= 1.0


def test_materials_replace_clears_followups():
    """材料替换(数据一致性):旧追问引用的事实已不存在,应同步清除。"""
    sid = _setup_session_with_findings()
    questions = followup_service.generate_from_findings(sid, [
        {"question": "问题1", "what_to_provide": "x", "why_needed": "y",
         "evidence_type": "explanation", "evidence_format": "文字",
         "uncertainty": 0.5, "change_probability": 0.5, "answer_cost": "medium"},
    ])
    followup_service.save_questions(sid, questions)
    assert len(followup_service.get_questions(sid)) == 1

    # 替换材料(replace 模式)
    evidence_chain.clear_materials(sid, "execution")

    # 追问已清除
    assert followup_service.get_questions(sid) == []