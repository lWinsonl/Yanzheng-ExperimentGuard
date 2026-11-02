"""Adversarial regression cases; these are not real-world accuracy estimates."""
import json

import pytest
from fastapi.testclient import TestClient

from app.agent.agent_service import agent_service
from app.agent.llm_client import llm_client
from app.main import app
from app.models.claim_graph import EdgeRelation, TestAspect as Aspect
from app.models.evidence import FactStatus
from app.models.followup import FollowupQuestion
from app.models.version_diff import MigrationQuestion
from app.services import claim_graph_service, data_store, evidence_chain, review_service
from app.services.followup import followup_service
from app.services.version_diff import version_diff_service


def session(claim="模型A优于基线B，对新设备更稳定"):
    return evidence_chain.create_session("可靠性回归", "data_model", [claim]).session_id


def ingest(sid, text, role="execution", filename="record.txt"):
    doc, facts, _ = evidence_chain.extract_from_text(sid, text, filename, role)
    for fact in facts:
        evidence_chain.confirm_fact(sid, fact.fact_id, "confirm")
    return doc, facts


def edges_for(sid, aspect):
    graph = claim_graph_service.build_graph(sid)
    sc = next(s for s in graph.sub_claims if s.test_aspect == aspect)
    return graph.edges_for_sub_claim(sc.sub_claim_id)


@pytest.mark.parametrize("text,role,aspect", [
    ("F1", "execution", Aspect.COMPARISON),
    ("基线为B", "execution", Aspect.BASELINE_FAIRNESS),
    ("重复运行5次，报告均值±标准差", "plan", Aspect.STABILITY),
    ("n_runs=5", "execution", Aspect.STABILITY),
    ("train_test_split(device_ids, test_size=0.2)", "execution", Aspect.SCOPE),
    ("GroupShuffleSplit(n_splits=5)", "execution", Aspect.SCOPE),
    ("按设备划分，设备不重叠", "plan", Aspect.SCOPE),
])
def test_related_materials_do_not_prove_claim(text, role, aspect):
    sid = session()
    ingest(sid, text, role)
    assert all(e.relation == EdgeRelation.UNKNOWN for e in edges_for(sid, aspect))


@pytest.mark.parametrize("train,test,role,expected", [
    (["A", "B"], ["C"], "execution", EdgeRelation.SUPPORTS),
    (["A", "B"], ["B"], "execution", EdgeRelation.CONTRADICTS),
    (["A"], ["B"], "plan", EdgeRelation.UNKNOWN),
    ([], ["B"], "execution", EdgeRelation.UNKNOWN),
    ([True], [False], "execution", EdgeRelation.UNKNOWN),
])
def test_explicit_entity_records_have_bounded_meaning(train, test, role, expected):
    sid = session()
    text = json.dumps({"train_entity_ids": train, "test_entity_ids": test})
    ingest(sid, text, role, "entities.json")
    assert expected in [e.relation for e in edges_for(sid, Aspect.SCOPE)]
    report = review_service.run_review(sid)
    findings = [f for f in report.findings if f.rule_id == "dm_claim_generalization"]
    if expected == EdgeRelation.CONTRADICTS:
        assert any(f.level.value == "contradiction" for f in findings)
    elif expected == EdgeRelation.SUPPORTS:
        assert not findings


def test_answer_confirmation_gate_and_actual_review_change():
    sid = session("模型A优于基线B")
    old = review_service.run_review(sid)
    target = next(f for f in old.findings if f.rule_id == "dm_baseline")
    q = FollowupQuestion(session_id=sid, question="补充基线设置", target_finding_id=target.finding_id)
    followup_service.save_questions(sid, [q])
    answered = followup_service.record_answer(sid, q.question_id, "基线为B，实际结果仍需上传")
    store = data_store.require(sid)
    assert store.docs[answered.answer_material_id].origin == "followup_answer"
    assert store.latest_report().report_id == old.report_id
    assert answered.answer_fact_ids
    assert all(store.facts[fid].status == FactStatus.PENDING for fid in answered.answer_fact_ids)
    with pytest.raises(ValueError, match="确认"):
        followup_service.review_answer(sid, q.question_id)
    for fid in answered.answer_fact_ids:
        evidence_chain.confirm_fact(sid, fid, "confirm")
    result = followup_service.review_answer(sid, q.question_id)
    assert result.review_state == "reviewed"
    assert result.answer_changed_finding
    assert store.baseline_report_id == old.report_id
    # A self-reported baseline changes the gap, but cannot clear the need for execution records.
    assert any(f.rule_id == "dm_baseline" for f in store.latest_report().findings)
    assert followup_service.record_answer(sid, q.question_id, q.answer_text).answer_material_id == q.answer_material_id


def test_rejected_answers_do_not_enter_review():
    sid = session()
    old = review_service.run_review(sid)
    q = FollowupQuestion(session_id=sid, question="请说明", target_finding_id=old.findings[0].finding_id)
    followup_service.save_questions(sid, [q])
    followup_service.record_answer(sid, q.question_id, "基线B")
    for fid in q.answer_fact_ids:
        evidence_chain.confirm_fact(sid, fid, "reject")
    followup_service.review_answer(sid, q.question_id)
    assert data_store.require(sid).latest_report().usable_fact_count == 0


def test_keyword_stuffing_never_gets_fallback_score(monkeypatch):
    monkeypatch.setattr(llm_client, "is_available", lambda: False)
    sid = session()
    q = MigrationQuestion(session_id=sid, question="为什么？", reference_answer="划分与泄漏")
    data_store.require(sid).migration_questions.append(q)
    answer = "泄漏 划分 基线 鲁棒 稳定 重复 多次 随机 分组 泛化 新。因为 所以 建议 修改。" * 5
    result = agent_service.score_migration_answer(sid, q.question_id, answer)
    assert result["answer"].total_score is None
    assert result["answer"].score_status == "feedback_only"
    assert version_diff_service.get_stats(sid).migration_total == 0


@pytest.mark.parametrize("value", ["1", True, float("nan"), float("inf"), -1, 1.1, None])
def test_invalid_model_scores_fall_back_without_crashing(monkeypatch, value):
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: "ignored")
    data = dict(identifies_core_issue=value, explains_why=0.7, proposes_fix=0.7,
                reasoning_quality=0.7, feedback="具体反馈")
    monkeypatch.setattr(llm_client, "parse_json_response", lambda _: data)
    sid = session()
    q = MigrationQuestion(session_id=sid, question="测试", reference_answer="划分")
    data_store.require(sid).migration_questions.append(q)
    result = agent_service.score_migration_answer(sid, q.question_id, "待评价回答")
    assert result["answer"].score_status == "feedback_only"
    assert result["answer"].total_score is None


def test_valid_model_feedback_is_not_mastery_certificate(monkeypatch):
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: "ignored")
    monkeypatch.setattr(llm_client, "parse_json_response", lambda _: dict(
        identifies_core_issue=0.8, explains_why=0.7, proposes_fix=0.6,
        reasoning_quality=0.5, feedback="识别了按作者划分的需要，但未说明如何核对编号。"))
    sid = session()
    q = MigrationQuestion(session_id=sid, question="测试")
    data_store.require(sid).migration_questions.append(q)
    result = agent_service.score_migration_answer(sid, q.question_id, "按作者划分")
    assert result["answer"].total_score == pytest.approx(0.65)
    assert result["answer"].score_status == "model_feedback"


def test_browser_isolation_confirmation_api_and_upload_limit():
    with TestClient(app) as a, TestClient(app) as b:
        response = a.post("/api/sessions", json={"title": "A", "claims": ["模型A优于B"]})
        assert response.status_code == 200
        sid = response.json()["session_id"]
        assert a.get(f"/api/sessions/{sid}").status_code == 200
        assert b.get(f"/api/sessions/{sid}").status_code == 404
        assert sid not in [s["session_id"] for s in b.get("/api/sessions").json()]
        old = review_service.run_review(sid)
        q = FollowupQuestion(session_id=sid, question="请说明", target_finding_id=old.findings[0].finding_id)
        followup_service.save_questions(sid, [q])
        url = f"/api/sessions/{sid}/followups/{q.question_id}"
        answered = a.post(url + "/answer", json={"answer_text": "基线B"})
        assert answered.status_code == 200
        assert a.post(url + "/review").status_code == 409
        for fid in answered.json()["answer_fact_ids"]:
            assert a.post(f"/api/sessions/{sid}/facts/{fid}/confirm", json={"action": "confirm"}).status_code == 200
        assert a.post(url + "/review").status_code == 200
        too_large = a.post(f"/api/sessions/{sid}/materials/upload", data={"role": "execution", "mode": "replace"},
                           files={"file": ("large.txt", b"x" * (5 * 1024 * 1024 + 1))})
        assert too_large.status_code == 413
        assert q.answer_material_id in data_store.require(sid).docs


def test_review_baseline_survives_intermediate_reviews():
    sid = session()
    first = review_service.run_review(sid)
    review_service.run_review(sid)
    diff = version_diff_service.run_version_diff(sid, "没有修改")
    assert diff.old_report_id == first.report_id
    assert data_store.require(sid).baseline_report_id == diff.new_report_id


def test_manual_correction_is_not_a_replacement_execution_record():
    sid = session()
    _, facts = ingest(sid, "train_test_split(device_ids, test_size=0.2)")
    for fact in facts:
        evidence_chain.confirm_fact(sid, fact.fact_id, "correct",
            '{"train_entity_ids":["A"],"test_entity_ids":["B"]}')
    assert all(e.relation == EdgeRelation.UNKNOWN for e in edges_for(sid, Aspect.SCOPE))


def test_self_reported_lists_are_not_independent_execution_proof():
    sid = session()
    q = FollowupQuestion(session_id=sid, question="请说明编号")
    followup_service.save_questions(sid, [q])
    followup_service.record_answer(sid, q.question_id,
        '{"train_entity_ids":["A"],"test_entity_ids":["B"]}')
    for fid in q.answer_fact_ids:
        evidence_chain.confirm_fact(sid, fid, "confirm")
    assert all(e.relation == EdgeRelation.UNKNOWN for e in edges_for(sid, Aspect.SCOPE))


def test_deep_review_cannot_bind_quote_to_wrong_file():
    sid = session()
    ingest(sid, "实际文本只在文件A中出现。", filename="A.txt")
    ingest(sid, "文件B中的其他内容。", filename="B.txt")
    result = agent_service._parse_deep_findings(data_store.require(sid), [{
        "title": "模型发现", "level": "contradiction", "quote": "实际文本只在文件A中出现",
        "material_filename": "B.txt", "reasoning": "待核对", "suggestion": "请补证据",
    }])
    assert not result[0].quote_verified
    assert result[0].level == "insufficient"
    assert result[0].verified_quote == ""


def test_demo_quotas_bound_requests_and_model_attempts():
    from app.access import DemoAccess
    limiter = DemoAccess()
    assert all(limiter.allow_write("owner") for _ in range(120))
    assert not limiter.allow_write("owner")
    assert all(limiter.allow_model("owner") for _ in range(60))
    assert not limiter.allow_model("owner")
    for owner in ("b", "c", "d"):
        assert all(limiter.allow_model(owner) for _ in range(60))
    assert not limiter.allow_model("another-browser")


def test_replaced_material_stays_available_as_historical_source():
    sid = session()
    old, _ = ingest(sid, "旧材料的实际内容。")
    report = review_service.run_review(sid)
    evidence_chain.clear_materials(sid, "execution")
    store = data_store.require(sid)
    assert old.material_id not in store.docs
    assert store.archived_docs[old.material_id].content == old.content
    assert report.report_id in store.reports


def test_old_rule_graph_is_rebuilt_before_display():
    sid = session()
    ingest(sid, "F1")
    graph = claim_graph_service.build_graph(sid)
    graph.rule_version = 1
    for edge in graph.edges:
        edge.relation = EdgeRelation.SUPPORTS
    rebuilt = claim_graph_service.get_graph(sid)
    assert rebuilt.rule_version >= 3
    assert all(edge.relation == EdgeRelation.UNKNOWN for edge in rebuilt.edges)
