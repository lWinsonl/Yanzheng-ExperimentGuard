"""Shared, environment-configured login for the public competition demo."""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE = "yanzheng_demo_auth"
TTL_SECONDS = 60 * 60 * 24 * 7


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


def is_configured() -> bool:
    return bool(settings.demo_username or settings.demo_password or settings.demo_auth_secret)


def _signature(expires: int) -> str:
    message = f"{settings.demo_username}.{expires}".encode()
    return hmac.new(settings.demo_auth_secret.encode(), message, hashlib.sha256).hexdigest()


def authenticated(request: Request) -> bool:
    if not is_configured():
        return True
    token = request.cookies.get(COOKIE, "")
    try:
        raw_expires, signature = token.split(".", 1)
        expires = int(raw_expires)
    except (ValueError, AttributeError):
        return False
    if expires < int(time.time()):
        return False
    return hmac.compare_digest(signature, _signature(expires))


@router.get("/status")
def status(request: Request):
    return {"login_required": is_configured(), "authenticated": authenticated(request)}


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    if not is_configured():
        return {"login_required": False, "authenticated": True}
    if not (settings.demo_username and settings.demo_password and settings.demo_auth_secret):
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="演示账号尚未完成服务端配置")
    username_ok = hmac.compare_digest(payload.username, settings.demo_username)
    password_ok = hmac.compare_digest(payload.password, settings.demo_password)
    if not (username_ok and password_ok):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="账号或密码不正确")
    expires = int(time.time()) + TTL_SECONDS
    token = f"{expires}.{_signature(expires)}"
    response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == "https",
                        samesite="strict", max_age=TTL_SECONDS, path="/")
    return {"login_required": True, "authenticated": True}


@router.post("/enter")
def enter(request: Request, response: Response):
    """One-click entry for the intentionally public competition demo account."""
    if not (settings.demo_username and settings.demo_password and settings.demo_auth_secret):
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="公开演示账号尚未完成服务端配置")
    expires = int(time.time()) + TTL_SECONDS
    token = f"{expires}.{_signature(expires)}"
    response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == "https",
                        samesite="strict", max_age=TTL_SECONDS, path="/")
    return {"login_required": True, "authenticated": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"authenticated": False}
