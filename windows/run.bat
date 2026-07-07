@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0..
if not exist .venv (
    echo Environment not found. Please run windows\install.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate
echo Starting VoidClaw...
python -m core.agent
pause
