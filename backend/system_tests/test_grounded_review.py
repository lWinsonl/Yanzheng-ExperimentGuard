"""Regression boundaries from the public pilot, not independent research quality estimates."""
import json

import pytest

from app.agent.agent_service import agent_service
from app.agent.llm_client import llm_client
from app.services import data_store, evidence_chain, review_service
from app.services.program_checks import parse_confusion_table
from app.services.review_context import build_context
from app.services.version_diff import version_diff_service
from .conftest import confirm, make_session, upload_text


def records(client, sid, train, test, scope="", mode="append"):
    record = {"train_entity_ids": train, "test_entity_ids": test}
    if scope:
        record["evaluation_scope"] = scope
    upload_text(client, sid, json.dumps(record), "entities.json", mode=mode)
    confirm(client, sid)


def proposal(context, kind="entity_isolation", level="contradiction"):
    c = next(c for c in context.checks if c.kind == kind)
    e = next(e for e in context.evidence if e.check_id == c.check_id)
    return dict(issue_kind=kind, level=level, title="编号交集需要处理", reasoning=c.basis,
                evidence_ids=[e.evidence_id], check_ids=[c.check_id], suggestion_type="fix",
                suggestion_action="按同源实体分组，再提供新编号记录", suggestion_verify="重新计算原图编号交集")


def model(monkeypatch, item):
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "chat", lambda *a, **kw: json.dumps({"deep_findings": [item]}, ensure_ascii=False))


def test_computed_overlap_survives_truncation_and_is_sent_to_model(client, monkeypatch):
    sid = make_session(client)
    records(client, sid, list(range(3000)), [2999, 3000])
    context = build_context(data_store.require(sid))
    assert context.coverage[0]["truncated"]
    assert context.checks[0].values["overlap_count"] == 1
    item = proposal(context)
    captured = {}
    def reply(system, user, **kwargs):
        captured.update(json.loads(user))
        return json.dumps({"deep_findings": [item]}, ensure_ascii=False)
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "chat", reply)
    result = agent_service.deep_review(sid)
    assert result.status == "ok" and result.findings[0].evidence_verified
    assert result.findings[0].validation_status == "awaiting_new_records"
    assert captured["review_context"]["program_checks"][0]["values"]["overlap_count"] == 1
    assert result.findings[0].verified_quote == ""  # Computed basis is not a fake original quote.


@pytest.mark.parametrize("change", ["unknown_evidence", "other_session", "invalid_level", "legacy_quote"])
def test_bad_bindings_never_keep_fix_actions(client, monkeypatch, change):
    sid = make_session(client)
    records(client, sid, [1, 2], [2, 3])
    ctx = build_context(data_store.require(sid))
    item = proposal(ctx)
    if change == "unknown_evidence": item["evidence_ids"] = ["ev_fake"]
    if change == "invalid_level": item["level"] = "everything_safe"
    if change == "legacy_quote":
        item.pop("evidence_ids")
        item.update(quote="train_entity_ids", material_filename="execution/entities.json")
    if change == "other_session":
        other = make_session(client)
        records(client, other, [1, 2], [2, 3])
        item["evidence_ids"] = [build_context(data_store.require(other)).evidence[0].evidence_id]
    model(monkeypatch, item)
    result = agent_service.deep_review(sid)
    assert result.status == "needs_evidence"
    assert not result.findings and result.unverified
    assert "按同源实体分组" not in json.dumps(result.unverified, ensure_ascii=False)


def test_passed_check_cannot_be_reaccused_by_model(client, monkeypatch):
    sid = make_session(client)
    records(client, sid, [1, 2], [3])
    model(monkeypatch, proposal(build_context(data_store.require(sid))))
    result = agent_service.deep_review(sid)
    assert not result.findings and result.unverified
    assert result.checks[0]["status"] == "passed"


def test_program_evidence_decides_kind_and_check_id_not_model_fields(client, monkeypatch):
    sid = make_session(client)
    records(client, sid, [1], [1])
    ctx = build_context(data_store.require(sid))
    item = proposal(ctx)
    item.update(issue_kind="comparison", check_ids=["check_invented_by_model"])
    model(monkeypatch, item)
    result = agent_service.deep_review(sid)
    assert result.findings[0].check_ids == [ctx.checks[0].check_id]
    assert "check_invented_by_model" not in json.dumps(result.findings[0].evidence)


def test_wrong_fix_does_not_replace_the_program_remediation_contract(client, monkeypatch):
    sid = make_session(client)
    records(client, sid, [1], [1])
    item = proposal(build_context(data_store.require(sid)))
    item["suggestion_action"] = "把复制4次改成复制2次即可消除泄漏"
    item["suggestion_verify"] = "两边准确率差不多就说明修复了"
    model(monkeypatch, item)
    result = agent_service.deep_review(sid)
    assert "按原始实体编号分组" in result.findings[0].suggestion_action
    assert "复制2次即可" not in result.findings[0].suggestion_action
    assert "交集为0" in result.findings[0].suggestion_verify


def test_unsupported_check_id_does_not_let_raw_text_override_a_pass(client, monkeypatch):
    sid = make_session(client)
    records(client, sid, [1], [2])
    ctx = build_context(data_store.require(sid))
    item = proposal(ctx)
    item.update(issue_kind="comparison", check_ids=["check_fake"])
    model(monkeypatch, item)
    assert not agent_service.deep_review(sid).findings


def test_absence_of_proof_only_requests_material_not_retraining(client, monkeypatch):
    sid = make_session(client)
    upload_text(client, sid, "accuracy=1.0", "run.log")
    ctx = build_context(data_store.require(sid))
    item = dict(issue_kind="entity_isolation", level="insufficient", title="缺编号", reasoning="只有准确率，未提供划分编号。",
        evidence_ids=[ctx.evidence[0].evidence_id], suggestion_type="fix", suggestion_action="删除所有测试数据并重训")
    model(monkeypatch, item)
    result = agent_service.deep_review(sid)
    assert result.findings[0].suggestion_type == "clarify"
    assert "重训" not in result.findings[0].suggestion_action


def test_unavailable_and_transport_failure_keep_checks(client, monkeypatch):
    sid = make_session(client)
    records(client, sid, [1], [1])
    result = agent_service.deep_review(sid)
    assert result.status == "llm_unavailable" and result.checks[0]["status"] == "failed"
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "chat", lambda *a, **kw: None)
    result = agent_service.deep_review(sid)
    assert result.status == "llm_call_failed" and result.checks


def test_zero_positive_recall_requires_confirmation_and_reaches_report(client):
    sid = make_session(client, "本次表格可以估计recall召回率。")
    upload_text(client, sid, "Observed,Predicted0,Predicted1\n0,134,30\n1,0,0\n", "matrix.csv")
    assert not review_service.run_review(sid).program_checks
    confirm(client, sid)
    report = review_service.run_review(sid)
    assert report.program_checks[0].values["recall"] is None
    assert any(f.rule_id == "binary_recall_denominator" for f in report.findings)


@pytest.mark.parametrize("raw", [
    "Observed,Predicted0,Predicted1\n0,10,2\n1,1,3,extra",
    "Observed,Predicted0,Predicted1\n0,10,2\n1,-1,3",
    "Observed,Predicted0,Predicted1\n0,10,2\n0,1,3",
    "Observed,Predicted0,Predicted1\n0,NaN,2\n1,1,3",
    "Observed,Predicted0,Predicted1\n0,1.5,2\n1,1,3",
    "Predicted,Observed0,Observed1\n0,10,2\n1,1,3",
])
def test_ambiguous_matrix_is_not_silently_reinterpreted(raw):
    assert parse_confusion_table(raw) is None


@pytest.mark.parametrize("scope,status", [("digits-v1", "passed_on_records"), ("", "scope_unconfirmed")])
def test_repair_pass_is_bounded_to_declared_scope(client, scope, status):
    sid = make_session(client)
    records(client, sid, [1, 2], [2, 3], scope)
    old = review_service.run_review(sid)
    records(client, sid, [1, 2], [3, 4], scope, mode="replace")
    new = review_service.run_review(sid)
    diff = version_diff_service.compute_diff(sid, old, new)
    assert diff.repair_checks[0]["status"] == status
    assert diff.repair_checks[0]["before_values"]["overlap_count"] == 1
    assert diff.repair_checks[0]["after_values"]["overlap_count"] == 0


def test_halving_repeats_with_remaining_overlap_does_not_validate_repair(client):
    sid = make_session(client)
    records(client, sid, [1, 2, 3], [2, 3, 4], "digits-v1")
    old = review_service.run_review(sid)
    records(client, sid, [1, 2], [2, 4], "digits-v1", mode="replace")
    diff = version_diff_service.compute_diff(sid, old, review_service.run_review(sid))
    assert diff.repair_checks[0]["status"] == "still_fails"


def test_deletion_unconfirmed_or_changed_scope_is_not_repair(client):
    sid = make_session(client)
    records(client, sid, [1], [1], "digits-v1")
    old = review_service.run_review(sid)
    evidence_chain.clear_materials(sid, "execution")
    empty = review_service.run_review(sid)
    assert version_diff_service.compute_diff(sid, old, empty).repair_checks[0]["status"] == "not_verified"
    records(client, sid, [1], [2], "other-dataset")
    diff = version_diff_service.compute_diff(sid, old, review_service.run_review(sid))
    assert diff.repair_checks[0]["status"] == "not_verified"


def test_full_raw_evidence_is_resolved_from_id_not_model_filename(client, monkeypatch):
    sid = make_session(client)
    upload_text(client, sid, 'replace outcome=1 if outcome==.\n', "score.txt")
    e = build_context(data_store.require(sid)).evidence[0]
    item = dict(issue_kind="target_semantics", level="risk", title="标签需核对", reasoning="缺失值被改为正类，需要对照定义。",
                evidence_ids=[e.evidence_id], material_filename="invented/path", quote="invented", suggestion_type="clarify")
    model(monkeypatch, item)
    result = agent_service.deep_review(sid)
    assert result.findings[0].material_filename == "score.txt"
    assert result.findings[0].verified_quote == e.text


def test_selected_coverage_reports_union_of_real_source_ranges(client):
    sid = make_session(client)
    upload_text(client, sid, "开头"*1500 + "F1=0.8" + "末尾"*1000, "long.log")
    confirm(client, sid)
    ctx = build_context(data_store.require(sid))
    c = ctx.coverage[0]
    assert c["selection_mode"] == "selected_evidence"
    assert c["checked_chars"] == sum(r["end_char"]-r["start_char"] for r in c["ranges"])
    assert any(r["start_char"] > 2000 for r in c["ranges"])


def test_inflight_material_change_discards_model_operations(client, monkeypatch):
    sid = make_session(client)
    records(client, sid, [1], [1])
    context = build_context(data_store.require(sid))
    item = proposal(context)
    def reply(*args, **kwargs):
        evidence_chain.clear_materials(sid, "execution")
        return json.dumps({"deep_findings": [item]})
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "chat", reply)
    result = agent_service.deep_review(sid)
    assert result.status == "needs_evidence" and not result.findings
    assert not result.checks
