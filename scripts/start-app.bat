@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo  AI 小说管理 - 桌面应用启动器
echo ============================================
echo.

pushd "%~dp0\.." >nul
set "PROJECT_DIR=%CD%"
popd >nul

set "EXE=%PROJECT_DIR%\src-tauri\target\release\ai-novel-desktop.exe"
set "PORT=8008"

if not exist "%EXE%" (
    echo [错误] 找不到应用: %EXE%
    echo 请先运行 build.bat 构建应用
    pause
    exit /b 1
)

echo [1/3] 检查后端端口 %PORT%...
netstat -ano | findstr ":%PORT% " >nul
if %errorlevel%==0 (
    echo       端口 %PORT% 已被占用,假设后端已运行
    goto :run_app
)

echo [2/3] 启动后端服务 (FastAPI)...
cd /d "%PROJECT_DIR%backend"
start "FastAPI-Backend" /min cmd /c "uv run main.py"
timeout /t 3 /nobreak >nul

:run_app
echo [3/3] 启动桌面应用...
cd /d "%PROJECT_DIR%"
start "" "%EXE%"

echo.
echo 应用已启动!
echo   - 桌面窗口已打开
echo   - 后端运行在 http://127.0.0.1:%PORT%
echo   - 关闭桌面窗口后,后端进程会保留
echo.
echo 提示: 如需停止后端服务,请在任务管理器结束 Python 进程
echo.
timeout /t 5 /nobreak >nul
exit /b 0
