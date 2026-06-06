@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================
echo  AI 小说管理 - 停止服务
echo ============================================
echo.

pushd "%~dp0\.." >nul
set "PROJECT_DIR=%CD%"
popd >nul

set "PORT=8008"
set "PID_DIR=%PROJECT_DIR%.run"
set "BACKEND_PID=%PID_DIR%\backend.pid"

REM ============================================
REM  [1/2] 关闭桌面应用
REM ============================================
echo [1/2] 关闭桌面应用...
set "KILLED_APP=0"
for /f "tokens=2" %%n in ('tasklist /FI "IMAGENAME eq ai-novel-desktop.exe" /NH 2^>nul ^| findstr /I "ai-novel-desktop"') do (
    echo       终止 ai-novel-desktop.exe ^(PID %%n^)
    taskkill /F /PID %%n >nul 2>&1
    set "KILLED_APP=1"
)
if !KILLED_APP!==0 echo       (无运行中的桌面应用)

REM ============================================
REM  [2/2] 关闭后端
REM ============================================
echo.
echo [2/2] 关闭后端服务...

REM 优先通过 PID 文件精确终止
set "KILLED_BE=0"
if exist "%BACKEND_PID%" (
    set /p SAVED_PID=<"%BACKEND_PID%"
    if defined SAVED_PID (
        tasklist /FI "PID eq !SAVED_PID!" /NH 2>nul | findstr /I "!SAVED_PID!" >nul
        if !errorlevel!==0 (
            echo       终止后端 ^(PID !SAVED_PID!^)
            taskkill /F /PID !SAVED_PID! >nul 2>&1
            set "KILLED_BE=1"
        )
    )
    del /f /q "%BACKEND_PID%" >nul 2>&1
)

REM 通过端口兜底 (兜底 uv 进程组,可能含多个)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo       终止占用端口 %PORT% 的进程 ^(PID %%p^)
    taskkill /F /PID %%p >nul 2>&1
    set "KILLED_BE=1"
)

REM 清理残余 uv / python 进程
for /f "tokens=2" %%n in ('tasklist /FI "IMAGENAME eq uv.exe" /NH 2^>nul ^| findstr /I "uv.exe"') do (
    echo       终止 uv.exe ^(PID %%n^)
    taskkill /F /PID %%n >nul 2>&1
)
for /f "tokens=2" %%n in ('tasklist /FI "IMAGENAME eq python.exe" /NH 2^>nul ^| findstr /I "python.exe"') do (
    echo       终止 python.exe ^(PID %%n^)
    taskkill /F /PID %%n >nul 2>&1
)

if !KILLED_BE!==0 echo       (无运行中的后端)

echo.
echo ============================================
echo  停止完成
echo ============================================
timeout /t 3 /nobreak >nul
exit /b 0
