@echo off
chcp 65001 >nul
title 中文长篇小说自动生成器 v1.0

echo.
echo ================================================================
echo     🌏  中文长篇小说自动生成器  v1.0
echo     基于 NousResearch/autonovel 重构
echo     支持: NVIDIA NIM / 硅基流动 / DeepSeek / 自定义
echo ================================================================
echo.

REM 检查 Python 是否可用
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 未找到 Python，请先安装 Python 3.9+
    echo    下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查依赖
python -c "import httpx" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ⚠ 缺少 httpx 库，正在安装 ...
    pip install httpx python-dotenv
    if %ERRORLEVEL% NEQ 0 (
        echo ❌ 依赖安装失败，请手动执行: pip install httpx python-dotenv
        pause
        exit /b 1
    )
)

echo 🚀 启动中 ...
echo.

cd /d "%~dp0"
python novel_app.py

echo.
echo ================================================================
echo   按任意键退出 ...
echo ================================================================
pause >nul