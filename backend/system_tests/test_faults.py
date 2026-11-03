import json

import pytest

from app.agent.agent_service import agent_service
from app.agent.llm_client import llm_client
from app.services import data_store
from .conftest import make_session, upload_text


@pytest.mark.parametrize("raw,status", [
    (None, "llm_call_failed"), ("not json", "llm_parse_failed"),
    ('{"unexpected": 1}', "llm_parse_failed"), ('{"deep_findings": []}', "ok_no_findings"),
])
def test_provider_failure_and_empty_success_are_distinct(client, monkeypatch, raw, status):
    sid = make_session(client)
    upload_text(client, sid, "F1=0.8", "result.log")
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: raw)
    response = client.post(f"/api/sessions/{sid}/agent/deep-review")
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert not response.json()["findings"]


def test_partial_coverage_is_reported_and_quote_is_bound_to_file(client, monkeypatch):
    sid = make_session(client)
    upload_text(client, sid, "可核对的首段原文。" + "后文" * 2000, "large.txt")
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    from app.services.review_context import build_context
    eid = build_context(data_store.require(sid)).evidence[0].evidence_id
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: json.dumps({"deep_findings": [{
        "title": "待检查", "level": "risk", "issue_kind": "other", "evidence_ids": [eid],
        "reasoning": "需要核实", "suggestion_action": "补充说明",
    }]}, ensure_ascii=False))
    result = client.post(f"/api/sessions/{sid}/agent/deep-review").json()
    assert result["coverage"][0]["truncated"]
    assert result["coverage"][0]["checked_chars"] < result["coverage"][0]["total_chars"]
    assert result["findings"][0]["quote_verified"]


def test_unicode_quotes_and_rejected_facts_remain_traceable(client):
    sid = make_session(client)
    uploaded = upload_text(client, sid, "设备甲🙂；评价指标为F1。", "中文材料.txt")
    prefix = f"/api/sessions/{sid}"
    facts = client.get(prefix + "/facts").json()
    assert facts
    doc = client.get(prefix + "/materials/" + uploaded["material_id"]).json()
    for fact in facts:
        span = fact["source"]
        assert doc["content"][span["start_char"]:span["end_char"]] == span["snippet"]
        assert client.post(prefix + f'/facts/{fact["fact_id"]}/confirm', json={"action": "reject"}).status_code == 200
    reviewed = client.post(prefix + "/review/run").json()
    assert reviewed["usable_fact_count"] == 0
    assert reviewed["skipped_fact_count"] == len(facts)


def test_model_failure_keeps_submitted_materials_and_reports(client, monkeypatch):
    sid = make_session(client)
    upload_text(client, sid, "基线为B，F1=0.8", "result.log")
    prefix = f"/api/sessions/{sid}"
    before = client.post(prefix + "/review/run").json()
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: None)
    assert client.post(prefix + "/agent/deep-review").json()["status"] == "llm_call_failed"
    assert len(client.get(prefix + "/materials").json()) == 1
    assert before["report_id"] in data_store.require(sid).reports


def test_deep_review_uses_its_configured_wait_and_thinking_budget(client, monkeypatch):
    from app.config import settings
    sid = make_session(client)
    upload_text(client, sid, "评价指标为F1。", "record.txt")
    monkeypatch.setattr(settings, "llm_review_timeout_seconds", 110)
    monkeypatch.setattr(settings, "llm_review_max_tokens", 7000)
    monkeypatch.setattr(settings, "llm_review_thinking", "enabled")
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    calls = []

    def chat(*args, **kwargs):
        calls.append(kwargs)
        return '{"deep_findings": []}'

    monkeypatch.setattr(llm_client, "chat", chat)
    result = client.post(f"/api/sessions/{sid}/agent/deep-review").json()
    assert result["status"] == "ok_no_findings"
    assert calls == [{"max_tokens": 7000, "timeout": 110, "retries": 0, "thinking": "enabled"}]
