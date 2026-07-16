@echo off
setlocal
cd /d "%~dp0.."
docker compose -p interview-agent up -d postgres redis
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
