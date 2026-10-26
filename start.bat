@echo off
REM 作文分身 · 一键启动（Windows）
REM 若 python 不在 PATH，请把下面改成你的 Python 完整路径
cd /d "%~dp0"
python backend\server.py %*
pause
