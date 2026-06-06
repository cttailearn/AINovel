@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo  AI 小说管理 - 开发模式
echo ============================================
echo.

pushd "%~dp0\.." >nul
set "PROJECT_DIR=%CD%"
popd >nul

set "CARGO_HTTP_CHECK_REVOKE=false"
set "CARGO_NET_GIT_FETCH_WITH_CLI=true"

REM ============================================
REM  [1/3] 启动后端
REM ============================================
echo [1/3] 检查后端端口 8008...
netstat -ano | findstr ":8008 " | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo       后端端口已被占用,假设后端已在运行
) else (
    echo [2/3] 启动后端服务 ^(FastAPI^)...
    cd /d "%PROJECT_DIR%backend"
    if not exist "main.py" (
        echo   [错误] 找不到 backend\main.py
        pause & exit /b 1
    )
    start "FastAPI-Backend" /min cmd /c "uv run main.py"
    timeout /t 3 /nobreak >nul
)

REM ============================================
REM  [3/3] 启动 Tauri dev
REM ============================================
echo.
echo [3/3] 启动 Tauri 开发模式 ^(含 Vite 热更新^)...
echo   - 修改 frontend/ 下的文件 → Vite HMR 自动刷新
echo   - 修改 src-tauri/ 下的 Rust 代码 → 自动重编译
echo   - 按 Ctrl+C 退出
echo.
cd /d "%PROJECT_DIR%src-tauri"
cargo tauri dev

pause
exit /b 0
