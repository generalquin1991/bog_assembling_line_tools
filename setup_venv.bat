@echo off
REM ESP烧录工具 - 虚拟环境设置脚本 (Windows)

echo 正在创建虚拟环境...
python -m venv venv

if %errorlevel% equ 0 (
    echo ✓ 虚拟环境创建成功！
    echo.
    echo ⚠️  重要：所有依赖（esptool, pyserial等）必须安装在虚拟环境中
    echo.
    echo 下一步操作：
    echo   1. 激活虚拟环境：
    echo      venv\Scripts\activate
    echo.
    echo   2. 在虚拟环境中安装依赖（看到 (venv) 提示符后）：
    echo      pip install -r requirements.txt
) else (
    echo ✗ 虚拟环境创建失败，请检查Python环境
    exit /b 1
)

