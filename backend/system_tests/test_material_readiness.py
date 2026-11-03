from app.agent.llm_client import llm_client
from .conftest import make_session, upload_text, confirm


def test_empty_materials_do_not_trigger_model_or_report_gaps(client, monkeypatch):
    sid = make_session(client)
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    result = client.post(f"/api/sessions/{sid}/agent/gaps").json()
    assert result["phase"] == "awaiting_materials"
    assert result["sufficiency"] == "unknown"
    assert result["gaps"] == []
    result = client.post(f"/api/sessions/{sid}/agent/deep-review").json()
    assert result["status"] == "needs_evidence"
    assert not result["findings"]


def test_pending_facts_are_not_misrepresented_as_missing(client, monkeypatch):
    sid = make_session(client)
    upload_text(client, sid, "计划使用F1作为评价指标。", "plan.md", "plan")
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    result = client.post(f"/api/sessions/{sid}/agent/gaps").json()
    assert result["phase"] == "awaiting_confirmation"
    assert result["gaps"] == []
    assert result["sufficiency"] == "unknown"
    monkeypatch.setattr(llm_client, "is_available", lambda: False)
    confirm(client, sid)
    result = client.post(f"/api/sessions/{sid}/agent/gaps").json()
    assert result["phase"] == "analyzed"
    assert any("执行" in gap["missing"] for gap in result["gaps"])
    assert not any(gap["missing"] == "评价指标" for gap in result["gaps"])


def test_replacing_materials_requires_fresh_confirmation(client):
    sid = make_session(client)
    upload_text(client, sid, "F1=0.8", "result.log")
    confirm(client, sid)
    assert client.post(f"/api/sessions/{sid}/agent/gaps").json()["phase"] == "analyzed"
    upload_text(client, sid, "F1=0.9", "replacement.log", mode="replace")
    result = client.post(f"/api/sessions/{sid}/agent/gaps").json()
    assert result["phase"] == "awaiting_confirmation"
    assert result["gaps"] == []
