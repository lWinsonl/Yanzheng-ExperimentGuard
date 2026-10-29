"""研证 - 服务端入口。

处理链:
    解析文件 -> 提取带出处的事实 -> 用户确认 -> 运行学科规则 -> 生成报告 -> 修改复查
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ALL_ROUTERS
from app.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in ALL_ROUTERS:
    app.include_router(router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name}