@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================
echo  AI 小说管理 - 桌面应用启动器
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
    echo [错误] 找不到应用: %EXE%
    echo 请先运行 build.bat 构建应用
    pause & exit /b 1
)

if not exist "%PID_DIR%" mkdir "%PID_DIR%"

REM ============================================
REM  [1/3] 启动后端
REM ============================================
echo [1/3] 检查后端端口 %PORT%...
set "BACKEND_RUNNING=0"
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo       端口 %PORT% 已被占用,假设后端已运行 ^(跳过启动^)
    set "BACKEND_RUNNING=1"
) else (
    echo [2/3] 启动后端服务 ^(FastAPI^)...
    if not exist "%PROJECT_DIR%backend\main.py" (
        echo   [错误] 找不到 backend\main.py
        pause & exit /b 1
    )
    cd /d "%PROJECT_DIR%backend"
    start "FastAPI-Backend" /min cmd /c "uv run main.py > "%BACKEND_LOG%" 2>&1"

    REM 等待端口就绪 (最多 20 秒)
    set "WAIT=0"
    :WAIT_PORT
    timeout /t 1 /nobreak >nul
    set /a WAIT+=1
    netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul
    if %errorlevel%==0 goto :PORT_READY
    if !WAIT! geq 20 (
        echo   [错误] 后端启动超时,请查看日志: %BACKEND_LOG%
        pause & exit /b 1
    )
    goto :WAIT_PORT
    :PORT_READY
    echo       后端已就绪 ^(等待 !WAIT! 秒^)

    REM 记录后端 PID (取 LISTENING 行的 PID)
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
        echo %%p > "%BACKEND_PID%"
    )
)

REM ============================================
REM  [3/3] 启动桌面应用
REM ============================================
echo [3/3] 启动桌面应用...
cd /d "%PROJECT_DIR%"
start "" "%EXE%"

echo.
echo ============================================
echo  应用已启动!
echo ============================================
echo   桌面窗口:    已打开
echo   后端地址:    http://127.0.0.1:%PORT%
echo   后端日志:    %BACKEND_LOG%
echo   后端 PID:    %BACKEND_PID%
echo.
echo 关闭桌面窗口后,后端进程会保留。
echo 停止应用请运行: scripts\stop-app.bat
echo ============================================
echo.
timeout /t 5 /nobreak >nul
exit /b 0
