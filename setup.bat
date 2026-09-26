@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM ============================================================
REM  First-time setup. Creates a local venv and installs the
REM  Python dependencies. Requires Python 3.11+ on PATH.
REM  ASCII-only paths are strongly recommended.
REM ============================================================

echo.
echo === WeChat toolkit setup ===
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [!] python not found on PATH.
  echo     Install Python 3.11+ from python.org and tick "Add to PATH".
  pause
  exit /b 1
)

echo [1/3] creating virtual environment (venv) ...
if not exist "venv" (
  python -m venv venv || (echo [!] venv creation failed & pause & exit /b 1)
) else (
  echo       already exists, reusing
)

set "PY=%~dp0venv\Scripts\python.exe"

echo [2/3] upgrading pip ...
"%PY%" -m pip install --quiet --upgrade pip -i https://pypi.org/simple

echo [3/3] installing dependencies ...
"%PY%" -m pip install -i https://pypi.org/simple frida pycryptodomex zstandard
if errorlevel 1 (
  echo [!] dependency install failed.
  echo     If you are behind a firewall, try again with a working network.
  pause
  exit /b 1
)

echo.
echo installing the engine (ChatTrace) ...
if not exist "engine\ChatTrace\pyproject.toml" (
  echo [!] engine\ChatTrace not found. See README.md.
  pause
  exit /b 1
)
"%PY%" -m pip install -i https://pypi.org/simple --no-deps -e ".\engine\ChatTrace"
if errorlevel 1 (
  echo [!] engine install failed.
  pause
  exit /b 1
)

echo.
echo === setup complete ===
echo   Now run:  start.bat
echo.
pause
