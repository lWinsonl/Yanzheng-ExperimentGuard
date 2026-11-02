"""Each system test owns temporary storage. Production files and provider calls are excluded."""
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.access import DemoAccess
from app.agent.llm_client import llm_client
from app.config import settings
from app.main import app
from app.services.store import data_store


@pytest.fixture(autouse=True)
def isolated_system(monkeypatch, tmp_path):
    monkeypatch.setattr(data_store, "_sessions", {})
    monkeypatch.setattr(data_store, "_data_dir", Path(tmp_path))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(llm_client, "is_available", lambda: False)
    monkeypatch.setattr(llm_client, "chat", Mock(side_effect=AssertionError("Unexpected provider call in offline system test")))
    # App middleware is a bound method on this instance; isolate its mutable counters.
    from app.access import demo_access
    fresh = DemoAccess()
    for name in ("_requests", "_total", "_model_requests", "_model_total"):
        monkeypatch.setattr(demo_access, name, getattr(fresh, name))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def make_session(client, claim="模型A优于基线B，可预测新设备"):
    response = client.post("/api/sessions", json={"title": "离线系统测试", "claims": [claim]})
    assert response.status_code == 200
    return response.json()["session_id"]


def upload_text(client, sid, text, filename="record.txt", role="execution", mode="append"):
    response = client.post(f"/api/sessions/{sid}/materials/text", json={
        "role": role, "filename": filename, "content": text, "mode": mode})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, sid):
    response = client.post(f"/api/sessions/{sid}/facts/confirm-all")
    assert response.status_code == 200
    return response.json()
