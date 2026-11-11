"""Public demo login prefill must not expose signing keys or merge browser owners."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.access import DemoAccess, current_owner
from app.api.auth import COOKIE, router
from app.config import settings


@pytest.fixture
def demo_app(monkeypatch):
    monkeypatch.setattr(settings, "demo_username", "judge")
    monkeypatch.setattr(settings, "demo_password", "公开演示密码")
    monkeypatch.setattr(settings, "demo_auth_secret", "private-signing-secret-for-tests-only")
    app = FastAPI()
    app.middleware("http")(DemoAccess().middleware)
    app.include_router(router)

    @app.get("/api/private")
    def private():
        return {"owner": current_owner.get()}

    return app


def test_public_prefill_exposes_only_demo_credentials(demo_app):
    with TestClient(demo_app) as client:
        response = client.get("/api/auth/status")
        value = response.json()
        assert value["demo_username"] == "judge"
        assert value["demo_password"] == "公开演示密码"
        assert value["authenticated"] is False
        assert settings.demo_auth_secret not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/private").status_code == 401


def test_prefilled_login_validates_edits_and_logout(demo_app):
    with TestClient(demo_app) as client:
        credentials = client.get("/api/auth/status").json()
        assert client.post("/api/auth/login", json={"username": "judge", "password": "wrong"}).status_code == 401
        assert client.get("/api/private").status_code == 401
        response = client.post("/api/auth/login", json={
            "username": credentials["demo_username"], "password": credentials["demo_password"],
        })
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"]
        assert client.get("/api/private").status_code == 200
        client.post("/api/auth/logout")
        assert client.get("/api/private").status_code == 401


def test_shared_login_keeps_different_browser_owners(demo_app):
    with TestClient(demo_app) as first, TestClient(demo_app) as second:
        for client in (first, second):
            client.post("/api/auth/login", json={"username": "judge", "password": "公开演示密码"})
        first_owner = first.get("/api/private").json()["owner"]
        second_owner = second.get("/api/private").json()["owner"]
        assert first_owner and second_owner and first_owner != second_owner


def test_partial_configuration_does_not_allow_forged_login(demo_app, monkeypatch):
    monkeypatch.setattr(settings, "demo_auth_secret", "")
    with TestClient(demo_app) as client:
        status = client.get("/api/auth/status").json()
        assert status["login_required"] and not status["authenticated"]
        assert status["demo_password"] == ""
        assert client.post("/api/auth/login", json={"username": "judge", "password": "公开演示密码"}).status_code == 503
        assert client.get("/api/private").status_code == 401


def test_tampered_cookie_cannot_open_review(demo_app):
    with TestClient(demo_app) as client:
        client.cookies.set(COOKIE, "9999999999.invalid-signature")
        assert client.get("/api/private").status_code == 401
