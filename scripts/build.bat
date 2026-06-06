@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo  AI 小说管理 - 桌面应用构建
echo ============================================
echo.

pushd "%~dp0\.." >nul
set "PROJECT_DIR=%CD%"
popd >nul

set "CARGO_HTTP_CHECK_REVOKE=false"
set "CARGO_NET_GIT_FETCH_WITH_CLI=true"

REM ============================================
REM  [1/4] 环境检查
REM ============================================
echo [1/4] 检查环境...

where cargo >nul 2>&1
if errorlevel 1 (
    echo   [错误] 未找到 cargo,请先安装 Rust: https://rustup.rs
    pause & exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo   [错误] 未找到 node,请先安装 Node.js
    pause & exit /b 1
)

where cargo-tauri >nul 2>&1
if errorlevel 1 (
    where cargo tauri >nul 2>&1
    if errorlevel 1 (
        echo   [警告] 未找到 tauri-cli,正在安装...
        call cargo install tauri-cli --version "^2.0" --locked
        if errorlevel 1 (
            echo   [错误] tauri-cli 安装失败
            pause & exit /b 1
        )
    )
)

for /f "delims=" %%v in ('cargo --version 2^>nul') do echo   cargo: %%v
for /f "delims=" %%v in ('node --version 2^>nul') do echo   node:  %%v

REM ============================================
REM  [2/4] 前端构建
REM ============================================
echo.
echo [2/4] 构建前端 (npm run build)...
cd /d "%PROJECT_DIR%frontend"
if not exist "node_modules" call npm install
if errorlevel 1 (
    echo   [错误] npm install 失败
    pause & exit /b 1
)
call npm run build
if errorlevel 1 (
    echo   [错误] 前端构建失败
    pause & exit /b 1
)
echo   前端产物: %PROJECT_DIR%frontend\dist

REM ============================================
REM  [3/4] Tauri 桌面构建 (含安装包)
REM ============================================
echo.
echo [3/4] 构建 Tauri 桌面应用 + 安装包 (cargo tauri build)...
echo   (首次构建会编译大量 Rust 依赖,可能需要 10-30 分钟)
cd /d "%PROJECT_DIR%src-tauri"
call cargo tauri build
if errorlevel 1 (
    echo   [错误] Tauri 构建失败
    pause & exit /b 1
)

REM ============================================
REM  [4/4] 产物汇总
REM ============================================
echo.
echo [4/4] 构建完成!
echo.
echo ============================================
echo  产物清单
echo ============================================
if exist "%PROJECT_DIR%src-tauri\target\release\ai-novel-desktop.exe" (
    echo   可执行文件:
    echo     %PROJECT_DIR%src-tauri\target\release\ai-novel-desktop.exe
)
echo.
if exist "%PROJECT_DIR%src-tauri\target\release\bundle" (
    echo   安装包:
    dir /b /s "%PROJECT_DIR%src-tauri\target\release\bundle"
) else (
    echo   安装包: ^(无,如需安装器请配置 tauri.conf.json.bundle^)
)
echo.
echo 启动应用: scripts\start-app.bat
echo ============================================
echo.
pause
exit /b 0
