#!/usr/bin/env python3
"""
保护 all_sn_logs.json 文件的工具脚本

功能：
1. 设置文件权限为只读（防止手动编辑）
2. 验证文件完整性
3. 显示文件保护状态

使用方法：
    python protect_sn_logs.py [--file all_sn_logs.json] [--verify] [--status]
"""

import os
import sys
import stat
import argparse
from pathlib import Path

# 数据目录与默认日志文件路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DEFAULT_SN_LOG_PATH = os.path.join(DATA_DIR, "all_sn_logs.json")

# 确保可以导入根目录下的 sn_generator 模块
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from sn_generator import verify_sn_logs
except ImportError as e:
    # 对于 SN 日志保护脚本，如果无法导入 sn_generator，就直接报错并退出，
    # 避免在无法校验完整性的情况下继续操作，降低 SN 重复风险。
    print("✗ 无法导入 sn_generator 模块，无法验证 SN 日志完整性。")
    print(f"  详细错误: {e}")
    print("  请确认当前目录下存在 sn_generator.py 且 Python 搜索路径正确，然后重试。")
    sys.exit(1)


def set_file_readonly(file_path: str) -> bool:
    """
    设置文件为只读
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否设置成功
    """
    if not os.path.exists(file_path):
        print(f"✗ 文件不存在: {file_path}")
        return False
    
    try:
        # 设置为只读：用户只读，组和其他只读
        os.chmod(file_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        print(f"✓ 文件权限已设置为只读: {file_path}")
        return True
    except (OSError, PermissionError) as e:
        print(f"✗ 设置文件权限失败: {e}")
        return False


def get_file_permissions(file_path: str) -> str:
    """
    获取文件权限字符串
    
    Args:
        file_path: 文件路径
        
    Returns:
        str: 权限字符串（如 "rw-r--r--"）
    """
    if not os.path.exists(file_path):
        return "文件不存在"
    
    try:
        file_stat = os.stat(file_path)
        mode = file_stat.st_mode
        
        # 转换为字符串格式
        perms = []
        perms.append('r' if mode & stat.S_IRUSR else '-')
        perms.append('w' if mode & stat.S_IWUSR else '-')
        perms.append('x' if mode & stat.S_IXUSR else '-')
        perms.append('r' if mode & stat.S_IRGRP else '-')
        perms.append('w' if mode & stat.S_IWGRP else '-')
        perms.append('x' if mode & stat.S_IXGRP else '-')
        perms.append('r' if mode & stat.S_IROTH else '-')
        perms.append('w' if mode & stat.S_IWOTH else '-')
        perms.append('x' if mode & stat.S_IXOTH else '-')
        
        return ''.join(perms)
    except Exception as e:
        return f"错误: {e}"


def show_file_status(file_path: str):
    """
    显示文件保护状态
    
    Args:
        file_path: 文件路径
    """
    if not os.path.exists(file_path):
        print(f"✗ 文件不存在: {file_path}")
        return
    
    file_stat = os.stat(file_path)
    perms = get_file_permissions(file_path)
    is_readonly = not (file_stat.st_mode & stat.S_IWUSR)
    
    print(f"\n文件: {file_path}")
    print(f"权限: {perms}")
    print(f"大小: {file_stat.st_size} 字节")
    print(f"只读: {'✓ 是' if is_readonly else '✗ 否'}")
    
    print("\n验证文件完整性:")
    is_valid, message = verify_sn_logs(file_path)
    print(f"  {message}")


def main():
    parser = argparse.ArgumentParser(
        description='保护 SN 日志文件 (all_sn_logs.json) 的工具脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 设置文件为只读
  python protect_sn_logs.py --file data/all_sn_logs.json
  
  # 验证文件完整性
  python protect_sn_logs.py --file data/all_sn_logs.json --verify
  
  # 显示文件状态
  python protect_sn_logs.py --file data/all_sn_logs.json --status
        """
    )
    
    parser.add_argument(
        '--file', '-f',
        type=str,
        default=DEFAULT_SN_LOG_PATH,
        help='日志文件路径（默认: data/all_sn_logs.json）'
    )
    
    parser.add_argument(
        '--protect', '-p',
        action='store_true',
        help='设置文件为只读（默认操作）'
    )
    
    parser.add_argument(
        '--verify', '-v',
        action='store_true',
        help='验证文件完整性'
    )
    
    parser.add_argument(
        '--status', '-s',
        action='store_true',
        help='显示文件保护状态'
    )
    
    args = parser.parse_args()
    
    file_path = args.file
    
    # 如果没有指定任何操作，默认执行保护操作
    if not any([args.protect, args.verify, args.status]):
        args.protect = True
    
    # 执行保护操作
    if args.protect:
        print("=" * 60)
        print("设置文件为只读...")
        print("=" * 60)
        if set_file_readonly(file_path):
            print("\n✓ 文件保护已启用")
            print("  注意: sn_generator 模块在需要写入时会自动临时修改权限")
        else:
            print("\n✗ 文件保护设置失败")
            return 1
    
    # 执行验证操作
    if args.verify:
        print("\n" + "=" * 60)
        print("验证文件完整性...")
        print("=" * 60)
        if SN_GENERATOR_AVAILABLE:
            is_valid, message = verify_sn_logs(file_path)
            print(f"\n{message}")
            if not is_valid:
                return 1
        else:
            print("\n✗ 无法验证文件完整性（sn_generator 模块不可用）")
            return 1
    
    # 显示状态
    if args.status:
        print("\n" + "=" * 60)
        print("文件保护状态")
        print("=" * 60)
        show_file_status(file_path)
    
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)

