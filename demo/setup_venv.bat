@echo off
echo ============================================
echo  银发传记 Demo - 虚拟环境初始化
echo ============================================

REM 检查 Python 版本
python --version
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.12
    pause
    exit /b 1
)

REM 创建虚拟环境
echo [1/3] 创建 venv 虚拟环境...
python -m venv venv

REM 激活虚拟环境
echo [2/3] 激活虚拟环境...
call venv\Scripts\activate.bat

REM 安装依赖
echo [3/3] 安装项目依赖...
pip install --upgrade pip
pip install -r requirements.txt

echo ============================================
echo  初始化完成！
echo.
echo  下一步：
echo   1. 复制 .env.example 为 .env
echo   2. 编辑 .env 填入 DashScope API Key
echo   3. 运行: python main.py
echo ============================================
pause