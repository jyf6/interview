@echo off
setlocal
cd /d "%~dp0.."
docker compose -p interview-agent up -d redis
