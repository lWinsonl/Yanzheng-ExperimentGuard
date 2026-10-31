"""生产启动入口:同时托管前端与 API,兼容云平台 PORT 环境变量。"""

import os

import uvicorn


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT 必须在 1 到 65535 之间")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, workers=1)
