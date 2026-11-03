"""Exercise real request construction without network calls or real keys."""
import io
import json
import urllib.error
import urllib.request

import pytest

from app.agent.llm_client import LlmClient
from app.config import settings


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-only-secret")
    monkeypatch.setattr(settings, "llm_base_url", "https://open.bigmodel.cn/api/paas/v4")
    monkeypatch.setattr(settings, "llm_model", "glm-4.7-flash")
    monkeypatch.setattr(settings, "llm_timeout_seconds", 60)
    monkeypatch.setattr(settings, "llm_thinking", "disabled")
    calls = []

    def respond(request, timeout):
        calls.append((json.loads(request.data), timeout))
        return io.BytesIO(json.dumps({"model": "glm-4.7-flash", "choices": [{
            "finish_reason": "stop", "message": {"content": '{"ok":true}'},
        }]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    return LlmClient(), calls


def test_glm_short_task_uses_configured_timeout_and_no_extra_thinking(transport, caplog):
    client, calls = transport
    with caplog.at_level("INFO", logger="llm_client"):
        assert client.chat("system", "user") == '{"ok":true}'
    assert calls[0][1] == 60
    assert calls[0][0]["thinking"] == {"type": "disabled"}
    assert "LLM response model=glm-4.7-flash finish_reason=stop" in caplog.text
    assert "test-only-secret" not in caplog.text


def test_deep_call_can_keep_thinking_and_use_a_larger_budget(transport):
    client, calls = transport
    client.chat("system", "user", timeout=120, max_tokens=8192, thinking="enabled")
    body, timeout = calls[0]
    assert (timeout, body["max_tokens"], body["thinking"]) == (120, 8192, {"type": "enabled"})


@pytest.mark.parametrize("model,url", [
    ("other-model", "https://open.bigmodel.cn/api/paas/v4"),
    ("glm-4.7-flash", "https://example.invalid/v1"),
])
def test_other_services_do_not_receive_zhipu_thinking_parameter(transport, monkeypatch, model, url):
    client, calls = transport
    monkeypatch.setattr(settings, "llm_model", model)
    monkeypatch.setattr(settings, "llm_base_url", url)
    client.chat("system", "user", thinking="enabled")
    assert "thinking" not in calls[0][0]


def test_http_business_code_is_logged_without_provider_body_or_key(transport, monkeypatch, caplog):
    client, _ = transport

    def fail(request, timeout):
        body = json.dumps({"error": {"code": "1302", "message": "test-only-secret private submitted text"}})
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(body.encode()))

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    assert client.chat("system", "user") is None
    assert "status=429 provider_code=1302" in caplog.text
    assert "test-only-secret" not in caplog.text
    assert "private submitted text" not in caplog.text


def test_read_timeout_is_not_reported_as_a_success(transport, monkeypatch, caplog):
    client, _ = transport

    def fail(request, timeout):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    assert client.chat("system", "user") is None
    assert "read operation timed out" in caplog.text


def test_partial_output_is_not_adopted_as_complete(transport, monkeypatch, caplog):
    client, _ = transport
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps({
        "choices": [{"finish_reason": "length", "message": {"content": '{"ok":true}'}}],
    }).encode()))
    assert client.chat("system", "user") is None
    assert "output truncated" in caplog.text
