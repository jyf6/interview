@echo off
setlocal
cd /d "%~dp0..\frontend"
"C:\Program Files\nodejs\node.exe" ".\node_modules\vite\bin\vite.js" --host 127.0.0.1 --port 5173 --strictPort
