#!/bin/bash
# ESP烧录工具 - 虚拟环境设置脚本

echo "正在创建虚拟环境..."
python3 -m venv venv

if [ $? -eq 0 ]; then
    echo "✓ 虚拟环境创建成功！"
    echo ""
    echo "⚠️  重要：所有依赖（esptool, pyserial等）必须安装在虚拟环境中"
    echo ""
    echo "下一步操作："
    echo "  1. 激活虚拟环境："
    echo "     source venv/bin/activate"
    echo ""
    echo "  2. 在虚拟环境中安装依赖（看到 (venv) 提示符后）："
    echo "     pip install -r requirements.txt"
    echo ""
    echo "或者使用别名（如果已设置）："
    echo "  start_bog    # 激活虚拟环境"
    echo "  install_bog  # 安装依赖"
else
    echo "✗ 虚拟环境创建失败，请检查Python环境"
    exit 1
fi

