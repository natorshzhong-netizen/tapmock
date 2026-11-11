@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] 创建虚拟环境并安装依赖...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
) else (
    echo [1/2] 已存在 .venv，跳过安装
)

echo [2/2] 录制 → 脱敏 → Mock 回放，并打开流量视图...
".venv\Scripts\python.exe" -m src.tapmock demo --open

pause
exit /b 0

:error
echo.
echo 启动失败，请检查上面的报错信息。
pause
exit /b 1
