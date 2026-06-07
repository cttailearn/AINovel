@echo off
REM ============================================================
REM  AI Novel Desktop - Build script
REM  Encoding: UTF-8 with BOM (required for cross-shell support)
REM ============================================================
chcp 65001 >nul
setlocal

echo ============================================
echo  AI Novel Desktop - Build
echo ============================================
echo.

pushd "%~dp0\.." >nul
set "PROJECT_DIR=%CD%"
popd >nul

set "CARGO_HTTP_CHECK_REVOKE=false"
set "CARGO_NET_GIT_FETCH_WITH_CLI=true"

REM ============================================
REM  [1/4] Environment check
REM ============================================
echo [1/4] Checking environment...

where cargo >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] cargo not found. Install Rust: https://rustup.rs
    pause & exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] node not found. Install Node.js
    pause & exit /b 1
)

where cargo-tauri >nul 2>&1
if errorlevel 1 (
    where cargo tauri >nul 2>&1
    if errorlevel 1 (
        echo   [WARN] tauri-cli not found, installing...
        call cargo install tauri-cli --version "^2.0" --locked
        if errorlevel 1 (
            echo   [ERROR] tauri-cli install failed
            pause & exit /b 1
        )
    )
)

for /f "delims=" %%v in ('cargo --version 2^>nul') do echo   cargo: %%v
for /f "delims=" %%v in ('node --version 2^>nul') do echo   node:  %%v

REM ============================================
REM  [2/4] Frontend build
REM ============================================
echo.
echo [2/4] Building frontend (npm run build)...
cd /d "%PROJECT_DIR%frontend"
if not exist "node_modules" call npm install
if errorlevel 1 (
    echo   [ERROR] npm install failed
    pause & exit /b 1
)
call npm run build
if errorlevel 1 (
    echo   [ERROR] Frontend build failed
    pause & exit /b 1
)
echo   Frontend output: %PROJECT_DIR%frontend\dist

REM ============================================
REM  [3/4] Tauri build (with installer)
REM ============================================
echo.
echo [3/4] Building Tauri app + installer (cargo tauri build)...
echo   (First build will compile many Rust deps, 10-30 min)
cd /d "%PROJECT_DIR%src-tauri"
call cargo tauri build
if errorlevel 1 (
    echo   [ERROR] Tauri build failed
    pause & exit /b 1
)

REM ============================================
REM  [4/4] Output summary
REM ============================================
echo.
echo [4/4] Build complete!
echo.
echo ============================================
echo  Output files
echo ============================================
if exist "%PROJECT_DIR%src-tauri\target\release\ai-novel-desktop.exe" (
    echo   Executable:
    echo     %PROJECT_DIR%src-tauri\target\release\ai-novel-desktop.exe
)
echo.
if exist "%PROJECT_DIR%src-tauri\target\release\bundle" (
    echo   Installers:
    dir /b /s "%PROJECT_DIR%src-tauri\target\release\bundle"
) else (
    echo   Installers: (none)
)
echo.
echo Run scripts\start-app.bat to launch.
echo ============================================
echo.
pause
exit /b 0
