@echo off
setlocal
cd /d "%~dp0.."
start "interview-backend" cmd /k ".\scripts\start-backend.bat"
start "interview-frontend" cmd /k ".\scripts\start-frontend.bat"
echo Backend:  http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:5173
