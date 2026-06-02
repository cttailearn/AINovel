@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo  AI 小说管理 - 桌面应用构建脚本
echo ============================================
echo.

pushd "%~dp0\.." >nul
set "PROJECT_DIR=%CD%"
popd >nul

set "CARGO_HTTP_CHECK_REVOKE=false"
set "CARGO_NET_GIT_FETCH_WITH_CLI=true"

echo [1/3] 检查环境...
where cargo >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 cargo,请先安装 Rust
    pause
    exit /b 1
)
where node >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 node,请先安装 Node.js
    pause
    exit /b 1
)

echo [2/3] 构建前端 (npm run build)...
cd /d "%PROJECT_DIR%frontend"
call npm run build
if errorlevel 1 (
    echo [错误] 前端构建失败
    pause
    exit /b 1
)

echo.
echo [3/3] 构建 Tauri 桌面应用 (cargo build --release)...
cd /d "%PROJECT_DIR%src-tauri"
cargo build --release
if errorlevel 1 (
    echo [错误] Tauri 构建失败
    pause
    exit /b 1
)

echo.
echo ============================================
echo  构建完成!
echo ============================================
echo.
echo 应用位置: %PROJECT_DIR%src-tauri\target\release\ai-novel-desktop.exe
echo.
echo 运行 start-app.bat 启动应用
echo.
pause
exit /b 0
