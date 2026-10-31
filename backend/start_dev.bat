@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 研证后端启动中... http://127.0.0.1:8002
python -m uvicorn app.main:app --host 127.0.0.1 --port 8002
pause