import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.store import DataStore, data_store
from .conftest import confirm, make_session, upload_text


def test_full_api_workflow_from_pending_evidence_to_revision_and_practice(client):
    sid = make_session(client)
    prefix = f"/api/sessions/{sid}"
    upload_text(client, sid, "计划按设备划分，基线B，F1。", "plan.md", "plan")
    original = upload_text(client, sid, json.dumps({"train_entity_ids": ["A", "B"], "test_entity_ids": ["B"]}), "entities.json")
    before = client.post(prefix + "/review/run").json()
    assert before["usable_fact_count"] == 0
    assert before["skipped_fact_count"] > 0
    assert not any(f["level"] == "contradiction" for f in before["findings"])
    confirm(client, sid)
    first = client.post(prefix + "/review/run").json()
    assert any(f["rule_id"] == "dm_claim_generalization" and f["level"] == "contradiction" for f in first["findings"])
    graph = client.post(prefix + "/claim-graph/build").json()
    assert any(e["relation"] == "contradicts" for e in graph["edges"])
    assert client.post(prefix + "/agent/deep-review").json()["status"] == "llm_unavailable"

    questions = client.post(prefix + "/followups/generate").json()["questions"]
    assert questions
    qid = questions[0]["question_id"]
    answer = client.post(prefix + f"/followups/{qid}/answer", json={"answer_text": "基线为B，运行日志待补充。"}).json()
    assert answer["review_state"] == "awaiting_confirmation"
    assert client.post(prefix + f"/followups/{qid}/review").status_code == 409
    confirm(client, sid)
    assert client.post(prefix + f"/followups/{qid}/review").json()["review_state"] == "reviewed"

    baseline = data_store.require(sid).baseline_report_id
    replacement = upload_text(client, sid, json.dumps({"train_entity_ids": ["A", "B"], "test_entity_ids": ["C"]}),
                              "entities-v2.json", mode="replace")
    confirm(client, sid)
    latest = client.post(prefix + "/review/run").json()
    assert data_store.require(sid).baseline_report_id == baseline
    assert not any(f["rule_id"] == "dm_claim_generalization" and f["level"] == "contradiction" for f in latest["findings"])
    diff = client.post(prefix + "/version-diff/run", json={"revision_note": "已修改设备编号划分"})
    assert diff.status_code == 200
    assert diff.json()["old_report_id"] == baseline
    assert client.get(prefix + "/materials/" + original["material_id"]).status_code == 200
    assert client.get(prefix + "/materials/" + replacement["material_id"]).status_code == 200

    migration = client.post(prefix + "/migration/generate").json()
    assert migration["question"] is not None
    result = client.post(prefix + f'/migration/{migration["question"]["question_id"]}/answer', json={"answer_text": "先核对实体编号交集，再讨论未见实体泛化。"}).json()
    assert result["answer"]["total_score"] is None
    assert result["answer"]["score_status"] == "feedback_only"
    # Simulate a new server repository reading the persisted files, not merely the current cache.
    restored = DataStore().require(sid)
    assert restored.owner_id == data_store.require(sid).owner_id
    assert restored.baseline_report_id == data_store.require(sid).baseline_report_id
    assert original["material_id"] in restored.archived_docs
    assert restored.migration_answers[-1].total_score is None


@pytest.mark.parametrize("suffix,method", [
    ("", "GET"), ("/materials", "GET"), ("/facts", "GET"), ("/review/latest", "GET"),
    ("/review/run", "POST"), ("/claim-graph/build", "POST"), ("/followups/generate", "POST"),
    ("/migration/generate", "POST"), ("/agent/status", "GET"), ("/version-diff/stats", "GET"),
])
def test_second_browser_cannot_read_or_modify_session(client, suffix, method):
    sid = make_session(client)
    with TestClient(app) as other:
        assert other.request(method, f"/api/sessions/{sid}" + suffix).status_code == 404


def test_cookie_and_restart_access_contract(client):
    sid = make_session(client)
    cookie = next(c for c in client.cookies.jar if c.name == "yanzheng_browser")
    assert cookie.has_nonstandard_attr("HttpOnly")
    assert cookie.get_nonstandard_attr("SameSite").lower() == "strict"
    assert sid in [s["session_id"] for s in client.get("/api/sessions").json()]
    client.cookies.clear()
    assert client.get(f"/api/sessions/{sid}").status_code == 404


def test_failed_empty_or_oversized_replacement_keeps_previous_material(client):
    sid = make_session(client)
    original = upload_text(client, sid, "F1=0.8", "original.log")
    prefix = f"/api/sessions/{sid}"
    for raw, expected in [(b"", 400), (b"x" * (5 * 1024 * 1024 + 1), 413)]:
        response = client.post(prefix + "/materials/upload", data={"role": "execution", "mode": "replace"}, files={"file": ("bad.txt", raw)})
        assert response.status_code == expected
        current = client.get(prefix + "/materials").json()
        assert [d["material_id"] for d in current] == [original["material_id"]]


def test_pathlike_filename_is_metadata_not_filesystem_target(client, tmp_path):
    sid = make_session(client)
    response = client.post(f"/api/sessions/{sid}/materials/upload", data={"role": "execution"},
                           files={"file": ("../../outside.py", b"seed=42")})
    assert response.status_code == 200
    assert not (tmp_path.parent / "outside.py").exists()


def test_same_answer_retry_is_idempotent(client):
    sid = make_session(client)
    prefix = f"/api/sessions/{sid}"
    client.post(prefix + "/review/run")
    q = client.post(prefix + "/followups/generate").json()["questions"][0]
    endpoint = prefix + f'/followups/{q["question_id"]}/answer'
    one = client.post(endpoint, json={"answer_text": "基线为B"}).json()
    two = client.post(endpoint, json={"answer_text": "基线为B"}).json()
    assert one["answer_material_id"] == two["answer_material_id"]
    assert len(client.get(prefix + "/materials").json()) == 1


def test_write_limit_does_not_block_health_or_existing_reads(client, monkeypatch):
    from app.access import demo_access
    sid = make_session(client)
    monkeypatch.setattr(demo_access, "allow_write", lambda owner: False)
    assert client.post(f"/api/sessions/{sid}/review/run").status_code == 429
    assert client.get(f"/api/sessions/{sid}").status_code == 200
    assert client.get("/api/health").status_code == 200
