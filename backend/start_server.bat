@echo off
title Gaokao App - Backend Server

echo ========================================
echo   Gaokao App - Backend Server Start
echo ========================================
echo.

REM ===== Python venv path =====
set PYTHON_EXE=C:\Users\Mayn\.workbuddy\binaries\python\envs\default\Scripts\python.exe

REM ===== LLM API Key (DeepSeek) =====
set LLM_API_KEY=sk-hgazhgdjmyywcugftkxeksagvqvddyxtxefbywvaarlbszwm

REM ===== Check if Python venv exists =====
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python venv not found:
    echo   %PYTHON_EXE%
    echo.
    echo Please run:
    echo   python -m venv "C:\Users\Mayn\.workbuddy\binaries\python\envs\default"
    echo   pip install fastapi uvicorn[standard] httpx
    echo.
    pause
    exit /b 1
)

REM ===== Change to script directory (backend dir) =====
cd /d "%~dp0"

echo [INFO] Working dir: %CD%
echo [INFO] Python:     %PYTHON_EXE%
echo [INFO] LLM API:   SiliconFlow Qwen2.5-7B (key loaded)
echo [INFO] Starting server...
echo.
echo ----------------------------------------
echo  URLs after startup:
echo    Frontend:  http://localhost:8000
echo    API docs:  http://localhost:8000/docs
echo    Health:    http://localhost:8000/api/health
echo ----------------------------------------
echo  Press Ctrl+C to stop
echo ========================================
echo.

"%PYTHON_EXE%" main.py

echo.
echo ========================================
echo  Server stopped (exit code: %ERRORLEVEL%)
echo ========================================
pause
