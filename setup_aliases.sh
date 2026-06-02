#!/bin/bash
# ESP烧录工具 - 别名设置脚本
# 使用方法: source setup_aliases.sh
# 支持 bash 和 zsh

# 获取脚本所在目录的绝对路径（兼容bash和zsh）
if [ -n "$ZSH_VERSION" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${(%):-%x}")" && pwd)"
elif [ -n "$BASH_VERSION" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
fi

# 说明：start_bog / flash_* 的「项目根目录」= 本文件所在目录。
# 若 ~/.zshrc 里 source 的是另一个路径（例如 assembling_line_tools），
# 则别名永远操作那个目录，不会自动指向 assembling_line_tools_recovered。

# esptool 5.x 需要 Python >= 3.10；优先使用较新的解释器
find_bog_python() {
    local candidates=(python3.13 python3.12 python3.11 python3.10 python3)
    local py version major minor

    for py in "${candidates[@]}"; do
        if ! command -v "$py" >/dev/null 2>&1; then
            continue
        fi
        version=$("$py" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null) || continue
        major=${version%%.*}
        minor=${version#*.}
        if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; }; then
            echo "$py"
            return 0
        fi
    done

    echo "✗ 错误: 需要 Python 3.10 或更高版本（esptool 5.x 要求）" >&2
    if command -v python3 >/dev/null 2>&1; then
        echo "  当前 python3: $(python3 --version 2>&1)" >&2
    else
        echo "  未找到 python3" >&2
    fi
    echo "  建议安装: brew install python@3.12" >&2
    return 1
}

venv_python_ok() {
    [ -x "venv/bin/python" ] && venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

ensure_bog_venv() {
    local bog_python

    bog_python=$(find_bog_python) || return 1

    if [ -d "venv" ] && ! venv_python_ok; then
        echo "检测到旧虚拟环境（Python < 3.10），正在重建..."
        rm -rf venv
    fi

    if [ ! -d "venv" ]; then
        echo "正在创建虚拟环境（使用 $bog_python）..."
        "$bog_python" -m venv venv || {
            echo "✗ 虚拟环境创建失败"
            return 1
        }
        echo "✓ 虚拟环境创建成功！"
    fi
}

# 设置虚拟环境的别名（自动创建并安装依赖）
setup_bog() {
    cd "$SCRIPT_DIR" || return 1
    if [ -d "venv" ]; then
        echo "虚拟环境已存在"
        echo "如需重新安装依赖，请运行: install_bog"
        return 0
    fi
    
    # 检查 requirements.txt 是否存在
    if [ ! -f "requirements.txt" ]; then
        echo "✗ 错误: 找不到 requirements.txt"
        return 1
    fi
    
    ensure_bog_venv || return 1
    echo ""
    echo "正在安装依赖（esptool, pyserial等）..."
    
    # 激活虚拟环境并安装依赖
    source venv/bin/activate
    pip install --upgrade pip > /dev/null 2>&1  # 静默升级pip
    pip install -r requirements.txt
    
    if [ $? -eq 0 ]; then
        echo "✓ 依赖安装成功！"
        echo ""
        echo "虚拟环境已准备就绪，运行 'start_bog' 激活虚拟环境即可使用"
        deactivate 2>/dev/null  # 退出虚拟环境
    else
        echo "✗ 依赖安装失败"
        deactivate 2>/dev/null
        return 1
    fi
}

# 启动/激活虚拟环境的别名（自动完成所有设置并启动主程序）
start_bog() {
    cd "$SCRIPT_DIR" || return 1
    
    # 检查 requirements.txt 是否存在
    if [ ! -f "requirements.txt" ]; then
        echo "✗ 错误: 找不到 requirements.txt"
        return 1
    fi
    
    # 如果虚拟环境不存在或 Python 版本过低，创建/重建它
    if [ ! -d "venv" ]; then
        echo "虚拟环境不存在，正在创建..."
    fi
    ensure_bog_venv || return 1
    
    # 激活虚拟环境
    source venv/bin/activate
    
    # 检查依赖是否已安装（通过检查 esptool、pyserial 和 inquirer 是否存在）
    NEED_INSTALL=false
    if ! python -c "import esptool" 2>/dev/null; then
        NEED_INSTALL=true
    fi
    if ! python -c "import serial" 2>/dev/null; then
        NEED_INSTALL=true
    fi
    if ! python -c "import inquirer" 2>/dev/null; then
        NEED_INSTALL=true
    fi
    
    if [ "$NEED_INSTALL" = true ]; then
        echo "依赖未安装，正在安装（esptool, pyserial, inquirer等）..."
        pip install --upgrade pip > /dev/null 2>&1  # 静默升级pip
        pip install -r requirements.txt
        if [ $? -ne 0 ]; then
            echo "✗ 依赖安装失败"
            deactivate 2>/dev/null
            return 1
        fi
        echo "✓ 依赖安装成功！"
    fi
    
    echo "✓ 虚拟环境已激活！"
    echo "当前目录: $(pwd)"
    echo ""
    
    # 检查主程序是否存在
    if [ ! -f "flash_esp.py" ]; then
        echo "✗ 错误: 找不到 flash_esp.py"
        echo "提示: 运行 'deactivate' 退出虚拟环境"
        return 1
    fi
    
    # 自动启动主程序（TUI交互界面）
    echo "正在启动ESP烧录工具（交互式界面）..."
    echo ""
    # 直接运行，无参数时会自动启动TUI
    python flash_esp.py
}

# 开发模式烧录（不加密）
flash_develop() {
    cd "$SCRIPT_DIR" || return 1
    if [ -z "$VIRTUAL_ENV" ]; then
        if [ -d "venv" ]; then
            source venv/bin/activate
        else
            echo "✗ 错误: 虚拟环境不存在，请先运行 start_bog"
            return 1
        fi
    fi
    echo "🔧 使用 DEVELOP 模式（开发模式，不加密）"
    python flash_esp.py --mode develop "$@"
}

# 生产模式烧录（加密）
flash_factory() {
    cd "$SCRIPT_DIR" || return 1
    if [ -z "$VIRTUAL_ENV" ]; then
        if [ -d "venv" ]; then
            source venv/bin/activate
        else
            echo "✗ 错误: 虚拟环境不存在，请先运行 start_bog"
            return 1
        fi
    fi
    echo "🏭 使用 FACTORY 模式（生产模式，加密）"
    python flash_esp.py --mode factory "$@"
}

# 安装/更新依赖的别名（可选，用于更新依赖）
install_bog() {
    cd "$SCRIPT_DIR" || return 1
    if [ ! -f "requirements.txt" ]; then
        echo "✗ 错误: 找不到 requirements.txt"
        return 1
    fi
    
    # 检查是否在虚拟环境中，如果不在则激活
    if [ -z "$VIRTUAL_ENV" ]; then
        if [ -d "venv" ]; then
            echo "正在激活虚拟环境..."
            source venv/bin/activate
        else
            echo "✗ 错误: 虚拟环境不存在，请先运行 setup_bog"
            return 1
        fi
    fi
    
    echo "正在安装/更新依赖（esptool, pyserial等）..."
    pip install --upgrade -r requirements.txt
    if [ $? -eq 0 ]; then
        echo "✓ 依赖安装/更新成功！"
    else
        echo "✗ 依赖安装失败"
        return 1
    fi
}

# 显示帮助信息
help_bog() {
    echo "ESP烧录工具别名帮助:"
    echo "  start_bog     - 一键启动：自动创建虚拟环境、安装依赖并激活（推荐）"
    echo "  setup_bog     - 手动创建虚拟环境并安装依赖（可选）"
    echo "  install_bog   - 更新依赖（可选，用于更新requirements.txt中的依赖）"
    echo "  flash_develop - 使用开发模式烧录（不加密）"
    echo "  flash_factory - 使用生产模式烧录（加密）"
    echo "  help_bog      - 显示此帮助信息"
    echo ""
    echo "完整使用流程:"
    echo "  1. start_bog                    # 一键启动（自动完成所有设置）"
    echo "  2. python flash_esp.py --list   # 列出串口"
    echo "  3. flash_develop                 # 开发模式烧录（不加密）"
    echo "  4. flash_factory                # 生产模式烧录（加密）"
    echo ""
    echo "模式说明:"
    echo "  - DEVELOP模式: 用于开发和调试，不加密，便于调试"
    echo "  - FACTORY模式: 用于量产，支持加密，更安全"
    echo ""
    echo "重要提示:"
    echo "  - start_bog 会自动检查并完成所有设置（创建虚拟环境、安装依赖）"
    echo "  - 所有依赖都安装在虚拟环境中，不会影响系统Python"
    echo "  - 看到 (venv) 提示符表示虚拟环境已激活"
    echo "  - 运行 'deactivate' 退出虚拟环境"
    echo ""
    echo "多份工程 / 换目录后「不好用」时:"
    echo "  - 别名绑定的是「你 source 的那份 setup_aliases.sh」所在文件夹"
    echo "  - 请编辑 ~/.zshrc：把 source 路径改成当前要用的仓库，再 source ~/.zshrc"
    echo "  - 或在本仓库目录执行: source \"\$(pwd)/setup_aliases.sh\""
}

echo "别名已设置（项目根: $SCRIPT_DIR）:"
echo "  start_bog     - 一键启动（自动完成所有设置）"
echo "  setup_bog     - 手动创建虚拟环境（可选）"
echo "  install_bog   - 更新依赖（可选）"
echo "  flash_develop - 开发模式烧录（不加密）"
echo "  flash_factory - 生产模式烧录（加密）"
echo "  help_bog      - 显示帮助信息"
echo ""
echo "提示: 这些别名仅在当前shell会话中有效"
echo "要永久使用，请将以下内容添加到 ~/.zshrc 或 ~/.bashrc:"
echo "  source $SCRIPT_DIR/setup_aliases.sh"

