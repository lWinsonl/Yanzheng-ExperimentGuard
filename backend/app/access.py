"""Browser-scoped demo access; no cross-browser session enumeration.

This is a possession cookie for a demo, not a user account system. Losing the
cookie loses access. Quotas are process-local and deliberately bound total work.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from contextvars import ContextVar
import hashlib
import re
import secrets
import threading
import time

from starlette.responses import JSONResponse

current_owner: ContextVar[str] = ContextVar("review_owner", default="")
COOKIE = "yanzheng_browser"


class DemoAccess:
    def __init__(self):
        self._lock = threading.Lock()
        self._requests = OrderedDict()
        self._total = deque()
        self._model_requests = OrderedDict()
        self._model_total = deque()

    def allow_model(self, owner: str) -> bool:
        """Count actual provider attempts, including retries, separately from API requests."""
        if not owner:
            return True  # Local CLI use; HTTP requests always have an owner context.
        with self._lock:
            now = time.monotonic()
            while self._model_total and self._model_total[0] <= now - 3600:
                self._model_total.popleft()
            queue = self._model_requests.setdefault(owner, deque())
            self._model_requests.move_to_end(owner)
            while queue and queue[0] <= now - 3600:
                queue.popleft()
            if len(queue) >= 60 or len(self._model_total) >= 240:
                return False
            queue.append(now)
            self._model_total.append(now)
            while len(self._model_requests) > 2048:
                self._model_requests.popitem(last=False)
            return True

    def allow_write(self, owner: str) -> bool:
        with self._lock:
            now = time.monotonic()
            while self._total and self._total[0] <= now - 3600:
                self._total.popleft()
            queue = self._requests.setdefault(owner, deque())
            self._requests.move_to_end(owner)
            while queue and queue[0] <= now - 3600:
                queue.popleft()
            if len(queue) >= 120 or len(self._total) >= 600:
                return False
            queue.append(now)
            self._total.append(now)
            while len(self._requests) > 2048:
                self._requests.popitem(last=False)
            return True

    async def middleware(self, request, call_next):
        from app.services.store import data_store

        if not request.url.path.startswith("/api/") or request.url.path == "/api/health":
            return await call_next(request)
        if request.url.path in {"/api/auth/status", "/api/auth/login", "/api/auth/enter", "/api/auth/logout"}:
            return await call_next(request)
        from app.api.auth import authenticated
        if not authenticated(request):
            return JSONResponse({"detail": "请先登录后使用研证。"}, status_code=401)
        token = request.cookies.get(COOKIE, "")
        new_cookie = not re.fullmatch(r"[a-f0-9]{64}", token)
        if new_cookie:
            token = secrets.token_hex(32)
        owner = hashlib.sha256(token.encode()).hexdigest()
        context = current_owner.set(owner)
        try:
            match = re.match(r"^/api/sessions/([^/]+)", request.url.path)
            if match:
                store = data_store.get(match[1])
                # Old sessions with no owner are intentionally not public.
                if store is None or store.owner_id != owner:
                    return JSONResponse({"detail": "会话不存在或不属于当前浏览器，请从首页新建审查。"}, status_code=404)
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                size = request.headers.get("content-length", "0")
                if not size.isdigit() or int(size) > 6 * 1024 * 1024:
                    return JSONResponse({"detail": "请求过大，单个文件请控制在 5 MB 以内。"}, status_code=413)
                if not self.allow_write(owner):
                    return JSONResponse({"detail": "演示服务本小时操作额度已用完，请稍后再试。"}, status_code=429,
                                        headers={"Retry-After": "3600"})
            response = await call_next(request)
            if new_cookie:
                # Production is same-origin; localhost remains usable over HTTP.
                response.set_cookie(COOKIE, token, httponly=True, samesite="strict",
                                    secure=request.url.scheme == "https", max_age=60 * 60 * 24 * 30)
            return response
        finally:
            current_owner.reset(context)


demo_access = DemoAccess()
