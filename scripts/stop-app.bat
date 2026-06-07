@echo off
REM ============================================================
REM  AI Novel Desktop - Stop script
REM ============================================================
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================
echo  AI Novel Desktop - Stop
echo ============================================
echo.

pushd "%~dp0\.." >nul
set "PROJECT_DIR=%CD%"
popd >nul

set "PORT=8008"
set "PID_DIR=%PROJECT_DIR%.run"
set "BACKEND_PID=%PID_DIR%\backend.pid"

REM ============================================
REM  [1/2] Stop desktop app
REM ============================================
echo [1/2] Stopping desktop app...
set "KILLED_APP=0"
for /f "tokens=2" %%n in ('tasklist /FI "IMAGENAME eq ai-novel-desktop.exe" /NH 2^>nul ^| findstr /I "ai-novel-desktop"') do (
    echo       Killing ai-novel-desktop.exe ^(PID %%n^)
    taskkill /F /PID %%n >nul 2>&1
    set "KILLED_APP=1"
)
if !KILLED_APP!==0 echo       (no desktop app running)

REM ============================================
REM  [2/2] Stop backend
REM ============================================
echo.
echo [2/2] Stopping backend...

REM Prefer PID file for precise kill
set "KILLED_BE=0"
if exist "%BACKEND_PID%" (
    set /p SAVED_PID=<"%BACKEND_PID%"
    if defined SAVED_PID (
        tasklist /FI "PID eq !SAVED_PID!" /NH 2>nul | findstr /I "!SAVED_PID!" >nul
        if !errorlevel!==0 (
            echo       Killing backend ^(PID !SAVED_PID!^)
            taskkill /F /PID !SAVED_PID! >nul 2>&1
            set "KILLED_BE=1"
        )
    )
    del /f /q "%BACKEND_PID%" >nul 2>&1
)

REM Fallback: kill by port
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo       Killing port %PORT% holder ^(PID %%p^)
    taskkill /F /PID %%p >nul 2>&1
    set "KILLED_BE=1"
)

REM Cleanup residual uv / python
for /f "tokens=2" %%n in ('tasklist /FI "IMAGENAME eq uv.exe" /NH 2^>nul ^| findstr /I "uv.exe"') do (
    echo       Killing uv.exe ^(PID %%n^)
    taskkill /F /PID %%n >nul 2>&1
)
for /f "tokens=2" %%n in ('tasklist /FI "IMAGENAME eq python.exe" /NH 2^>nul ^| findstr /I "python.exe"') do (
    echo       Killing python.exe ^(PID %%n^)
    taskkill /F /PID %%n >nul 2>&1
)

if !KILLED_BE!==0 echo       (no backend running)

echo.
echo ============================================
echo  Stop complete
echo ============================================
timeout /t 3 /nobreak >nul
exit /b 0
