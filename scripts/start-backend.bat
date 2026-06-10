@echo off
setlocal
cd /d "%~dp0.."
".venv312\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
