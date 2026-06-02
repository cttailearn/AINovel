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

echo [1/3] 检查端口 8008...
netstat -ano | findstr ":8008 " >nul
if %errorlevel%==0 (
    echo       后端端口已被占用
) else (
    echo [2/3] 启动后端服务...
    cd /d "%PROJECT_DIR%backend"
    start "FastAPI-Backend" /min cmd /c "uv run main.py"
    timeout /t 3 /nobreak >nul
)

echo [3/3] 启动 Tauri 开发模式 (含热更新)...
echo       修改 frontend/ 下的文件会自动刷新
echo       修改 src-tauri/ 下的文件需要重新编译
echo       按 Ctrl+C 退出
echo.
cd /d "%PROJECT_DIR%src-tauri"
cargo tauri dev

pause
exit /b 0
