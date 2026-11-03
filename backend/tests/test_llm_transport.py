"""Exercise real request construction without network calls or real keys."""
import io
import json
import urllib.error
import urllib.request

import pytest

from app.agent.llm_client import LlmClient
from app.config import settings
from app.agent.call_diagnostics import capture_call_diagnostics


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


@pytest.mark.parametrize("status,code,kind,retryable", [
    (429, "1305", "provider_busy", True),
    (429, "1302", "rate_limited", True),
    (429, "1113", "account_limit", False),
    (401, "1000", "authentication", False),
    (403, "1220", "permission", False),
])
def test_failure_detail_is_safe_and_specific(transport, monkeypatch, status, code, kind, retryable):
    client, _ = transport

    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(json.dumps({
            "error": {"code": code, "message": "private submitted text test-only-secret"},
        }).encode()))

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with capture_call_diagnostics() as diagnostics:
        assert client.chat("system", "user") is None
    assert diagnostics.requested_model == "glm-4.7-flash"
    assert diagnostics.error.kind == kind
    assert diagnostics.error.provider_code == code
    assert diagnostics.error.retryable is retryable
    assert "private" not in diagnostics.error.message
    assert "secret" not in diagnostics.error.message


def test_model_override_is_local_and_response_model_is_reported(transport):
    client, calls = transport
    with capture_call_diagnostics() as diagnostics:
        client.chat("system", "user", model="glm-4-flash")
    assert calls[0][0]["model"] == "glm-4-flash"
    assert settings.llm_model == "glm-4.7-flash"
    assert diagnostics.error is None
    assert diagnostics.response_model == "glm-4.7-flash"  # The mock response, not a guess from the request.


def test_concurrent_diagnostics_do_not_leak_between_requests(transport, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    client, _ = transport
    barrier = Barrier(2)

    def respond(request, timeout):
        model = json.loads(request.data)["model"]
        barrier.wait(timeout=5)
        if model == "busy-model":
            raise urllib.error.HTTPError(request.full_url, 429, "busy", {},
                                         io.BytesIO(b'{"error":{"code":"1305"}}'))
        return io.BytesIO(json.dumps({"model": model, "choices": [{"message": {"content": "ok"}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", respond)

    def run(model):
        with capture_call_diagnostics() as diagnostics:
            client.chat("system", "user", model=model)
        return diagnostics

    with ThreadPoolExecutor(max_workers=2) as executor:
        busy, good = list(executor.map(run, ("busy-model", "good-model")))
    assert busy.error.kind == "provider_busy"
    assert busy.requested_model == "busy-model"
    assert good.error is None
    assert good.requested_model == good.response_model == "good-model"
