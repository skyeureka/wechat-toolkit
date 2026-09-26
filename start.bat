@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  WeChat 4.x chat-history toolkit (Windows) -- one-click start
REM  Offline / local only. Nothing leaves this machine.
REM ============================================================

set "PY=%~dp0venv\Scripts\python.exe"

if not exist "%PY%" (
  echo.
  echo [!] Python environment not found: %PY%
  echo.
  echo     Run setup.bat once to create it.
  echo.
  pause
  exit /b 1
)

set PYTHONIOENCODING=utf-8

"%PY%" run.py %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo [!] exited with code %RC%
  pause
)
endlocal & exit /b %RC%
