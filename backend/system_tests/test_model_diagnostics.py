import io
import json
import urllib.error
import urllib.request

import pytest

from app.agent.llm_client import LlmClient, llm_client
from app.config import settings
from .conftest import make_session, upload_text


def setup_transport(client, monkeypatch):
    sid = make_session(client)
    upload_text(client, sid, "F1=0.8", "record.log")
    monkeypatch.setattr(settings, "llm_api_key", "test-only-secret")
    monkeypatch.setattr(settings, "llm_base_url", "https://open.bigmodel.cn/api/paas/v4")
    monkeypatch.setattr(settings, "llm_model", "glm-4.7-flash")
    monkeypatch.setattr(settings, "llm_fallback_model", "")
    monkeypatch.setattr(llm_client, "is_available", lambda: True)
    monkeypatch.setattr(llm_client, "chat", LlmClient().chat)
    return sid


@pytest.mark.parametrize("error,kind", [
    (TimeoutError("The read operation timed out"), "timeout"),
    (urllib.error.URLError("SSL failed private detail"), "network"),
])
def test_call_failure_detail_reaches_api_without_exposing_raw_error(client, monkeypatch, error, kind):
    sid = setup_transport(client, monkeypatch)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    result = client.post(f"/api/sessions/{sid}/agent/deep-review").json()
    assert result["status"] == "llm_call_failed"
    assert result["requested_model"] == "glm-4.7-flash"
    assert result["call_error"]["kind"] == kind
    assert result["fallback_model"] == "glm-4-flash"
    assert "private" not in json.dumps(result)


def test_busy_primary_does_not_auto_switch_and_manual_fallback_uses_same_validation(client, monkeypatch):
    sid = setup_transport(client, monkeypatch)
    calls = []

    def respond(request, timeout):
        model = json.loads(request.data)["model"]
        calls.append(model)
        if model == "glm-4.7-flash":
            raise urllib.error.HTTPError(request.full_url, 429, "busy", {},
                io.BytesIO(b'{"error":{"code":"1305","message":"private test-only-secret"}}'))
        return io.BytesIO(json.dumps({"model": model, "choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"deep_findings": [{"title": "unsupported", "evidence_ids": ["invented"]}]}),
        }}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    primary = client.post(f"/api/sessions/{sid}/agent/deep-review").json()
    assert calls == ["glm-4.7-flash"]
    assert primary["call_error"]["provider_code"] == "1305"
    assert not primary["used_fallback"]
    fallback = client.post(f"/api/sessions/{sid}/agent/deep-review?use_fallback=true").json()
    assert calls == ["glm-4.7-flash", "glm-4-flash"]
    assert fallback["requested_model"] == fallback["response_model"] == "glm-4-flash"
    assert fallback["used_fallback"]
    assert fallback["status"] == "needs_evidence"
    assert not fallback["findings"]
    assert fallback["unverified"]
    assert settings.llm_model == "glm-4.7-flash"
    assert "test-only-secret" not in json.dumps(primary)


def test_unconfigured_fallback_makes_no_request(client, monkeypatch):
    sid = make_session(client)
    upload_text(client, sid, "F1=0.8", "record.log")
    monkeypatch.setattr(settings, "llm_model", "other-model")
    monkeypatch.setattr(settings, "llm_fallback_model", "")
    result = client.post(f"/api/sessions/{sid}/agent/deep-review?use_fallback=true").json()
    assert result["call_error"]["kind"] == "unconfigured"
    assert not result["response_model"]
