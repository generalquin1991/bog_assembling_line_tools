#!/bin/bash
# ESP烧录工具 - 永久安装别名到shell配置文件

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALIAS_FILE="$SCRIPT_DIR/setup_aliases.sh"

# 检测shell类型
if [ -n "$ZSH_VERSION" ]; then
    SHELL_RC="$HOME/.zshrc"
    SHELL_NAME="zsh"
elif [ -n "$BASH_VERSION" ]; then
    SHELL_RC="$HOME/.bashrc"
    SHELL_NAME="bash"
else
    echo "无法检测shell类型，默认使用 .zshrc"
    SHELL_RC="$HOME/.zshrc"
    SHELL_NAME="zsh"
fi

# 检查是否已经添加
if grep -q "setup_aliases.sh" "$SHELL_RC" 2>/dev/null; then
    echo "别名已经添加到 $SHELL_RC"
    echo "如果别名不工作，请运行: source $SHELL_RC"
else
    # 添加别名配置
    echo "" >> "$SHELL_RC"
    echo "# ESP烧录工具别名" >> "$SHELL_RC"
    echo "source \"$ALIAS_FILE\"" >> "$SHELL_RC"
    echo "别名已添加到 $SHELL_RC"
    echo "请运行以下命令使别名生效:"
    echo "  source $SHELL_RC"
    echo ""
    echo "或者重新打开终端"
fi

