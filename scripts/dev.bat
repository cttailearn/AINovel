@echo off
REM ============================================================
REM  AI Novel Desktop - Development mode
REM ============================================================
chcp 65001 >nul
setlocal

echo ============================================
echo  AI Novel Desktop - Dev mode
echo ============================================
echo.

pushd "%~dp0\.." >nul
set "PROJECT_DIR=%CD%"
popd >nul

set "CARGO_HTTP_CHECK_REVOKE=false"
set "CARGO_NET_GIT_FETCH_WITH_CLI=true"

REM ============================================
REM  [1/3] Start backend
REM ============================================
echo [1/3] Checking backend port 8008...
netstat -ano | findstr ":8008 " | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo       Backend port in use, assuming backend running
) else (
    echo [2/3] Starting backend ^(FastAPI^)...
    cd /d "%PROJECT_DIR%backend"
    if not exist "main.py" (
        echo   [ERROR] backend\main.py not found
        pause & exit /b 1
    )
    start "FastAPI-Backend" /min cmd /c "uv run main.py"
    timeout /t 3 /nobreak >nul
)

REM ============================================
REM  [3/3] Start Tauri dev
REM ============================================
echo.
echo [3/3] Starting Tauri dev ^(with Vite HMR^)...
echo   - Edit frontend/ files -> Vite HMR auto-reload
echo   - Edit src-tauri/ Rust code -> auto-recompile
echo   - Press Ctrl+C to exit
echo.
cd /d "%PROJECT_DIR%src-tauri"
cargo tauri dev

pause
exit /b 0
