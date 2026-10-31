# ---- 阶段1:构建前端 ----
FROM node:22-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 阶段2:Python 运行时(同源托管前端产物 + API) ----
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /build/dist ./static

# 默认 8080;云平台可通过 PORT 指定端口。保持单 worker,与当前 JSON 存储一致。
EXPOSE 8080
CMD ["python", "start_server.py"]
