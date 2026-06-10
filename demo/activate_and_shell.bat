@echo off
cd /d d:\simple\demo
call venv\Scripts\activate.bat
echo ============================================
echo  虚拟环境已激活！
echo  Python: 
python --version
echo  启动服务: python main.py
echo ============================================
cmd /k