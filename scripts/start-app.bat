@echo off
REM ============================================================
REM  AI Novel Desktop - App launcher
REM ============================================================
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================
echo  AI Novel Desktop - Launcher
echo ============================================
echo.

pushd "%~dp0\.." >nul
set "PROJECT_DIR=%CD%"
popd >nul

set "EXE=%PROJECT_DIR%\src-tauri\target\release\ai-novel-desktop.exe"
set "PORT=8008"
set "PID_DIR=%PROJECT_DIR%.run"
set "BACKEND_PID=%PID_DIR%\backend.pid"
set "BACKEND_LOG=%PID_DIR%\backend.log"

if not exist "%EXE%" (
    echo [ERROR] Application not found: %EXE%
    echo Please run build.bat first.
    pause & exit /b 1
)

if not exist "%PID_DIR%" mkdir "%PID_DIR%"

REM ============================================
REM  [1/3] Start backend
REM ============================================
echo [1/3] Checking backend port %PORT%...
set "BACKEND_RUNNING=0"
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo       Port %PORT% in use, assuming backend running ^(skip^)
    set "BACKEND_RUNNING=1"
) else (
    echo [2/3] Starting backend ^(FastAPI^)...
    if not exist "%PROJECT_DIR%backend\main.py" (
        echo   [ERROR] backend\main.py not found
        pause & exit /b 1
    )
    cd /d "%PROJECT_DIR%backend"
    start "FastAPI-Backend" /min cmd /c "uv run main.py > "%BACKEND_LOG%" 2>&1"

    REM Wait for port (max 20s)
    set "WAIT=0"
    :WAIT_PORT
    timeout /t 1 /nobreak >nul
    set /a WAIT+=1
    netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul
    if %errorlevel%==0 goto :PORT_READY
    if !WAIT! geq 20 (
        echo   [ERROR] Backend startup timeout. Check log: %BACKEND_LOG%
        pause & exit /b 1
    )
    goto :WAIT_PORT
    :PORT_READY
    echo       Backend ready ^(waited !WAIT!s^)

    REM Save backend PID
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
        echo %%p > "%BACKEND_PID%"
    )
)

REM ============================================
REM  [3/3] Launch desktop app
REM ============================================
echo [3/3] Launching desktop app...
cd /d "%PROJECT_DIR%"
start "" "%EXE%"

echo.
echo ============================================
echo  App started!
echo ============================================
echo   Desktop window:  opened
echo   Backend URL:     http://127.0.0.1:%PORT%
echo   Backend log:     %BACKEND_LOG%
echo   Backend PID:     %BACKEND_PID%
echo.
echo Backend keeps running after closing the desktop window.
echo Run scripts\stop-app.bat to stop everything.
echo ============================================
echo.
timeout /t 5 /nobreak >nul
exit /b 0
