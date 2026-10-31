"""研证 - 服务端入口。

处理链:
    解析文件 -> 提取带出处的事实 -> 用户确认 -> 运行学科规则 -> 生成报告 -> 修改复查

部署:生产单容器模式下,本服务同时托管前端构建产物(同源,/api 走后端、/ 走静态页);
本地开发时 static_dir 不存在,前端由 Vite 开发服务器代理 /api 到本服务。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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


# 生产模式:托管前端构建产物(须在所有 API 路由之后挂载,/api/* 优先匹配)
_static_dir = Path(settings.static_dir)
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")