#!/usr/bin/env python3
"""
测试文件访问权限管理

演示如何使用上下文管理器获取文件操作权限
"""

import sn_generator

def test_without_permission():
    """测试未获取权限时的行为"""
    print("=" * 60)
    print("测试 1: 未获取权限时调用函数")
    print("=" * 60)
    
    try:
        # 尝试在没有权限的情况下加载日志
        logs = sn_generator.load_sn_logs()
        print(f"✓ 成功加载 {len(logs)} 条日志")
    except sn_generator.FileAccessError as e:
        print(f"✗ 预期错误: {e}")
    except Exception as e:
        print(f"✗ 意外错误: {e}")


def test_with_permission():
    """测试获取权限后的行为"""
    print("\n" + "=" * 60)
    print("测试 2: 使用上下文管理器获取权限")
    print("=" * 60)
    
    try:
        with sn_generator.file_access():
            print("✓ 成功获取文件访问权限")
            
            # 尝试加载日志
            logs = sn_generator.load_sn_logs()
            print(f"✓ 成功加载 {len(logs)} 条日志")
            
            # 尝试生成序列号
            try:
                sn = sn_generator.generate_sn()
                print(f"✓ 成功生成序列号: {sn}")
            except Exception as e:
                print(f"⚠️  生成序列号时出错: {e}")
        
        print("✓ 权限已自动释放")
    except Exception as e:
        print(f"✗ 错误: {e}")


def test_nested_access():
    """测试嵌套使用"""
    print("\n" + "=" * 60)
    print("测试 3: 嵌套使用上下文管理器")
    print("=" * 60)
    
    try:
        with sn_generator.file_access():
            print("✓ 外层: 获取权限")
            
            with sn_generator.file_access():
                print("✓ 内层: 嵌套获取权限（应该成功）")
                
                logs = sn_generator.load_sn_logs()
                print(f"✓ 成功加载 {len(logs)} 条日志")
            
            print("✓ 内层: 权限释放（但外层仍持有）")
            
            # 外层仍应能访问
            logs = sn_generator.load_sn_logs()
            print(f"✓ 外层仍可访问: {len(logs)} 条日志")
        
        print("✓ 外层: 权限已释放")
    except Exception as e:
        print(f"✗ 错误: {e}")


def test_exception_safety():
    """测试异常安全性"""
    print("\n" + "=" * 60)
    print("测试 4: 异常安全性（确保权限会被释放）")
    print("=" * 60)
    
    try:
        with sn_generator.file_access():
            print("✓ 获取权限")
            print("  模拟异常...")
            raise ValueError("测试异常")
    except ValueError as e:
        print(f"✓ 捕获异常: {e}")
    
    # 检查权限是否已释放
    try:
        sn_generator.load_sn_logs()
        print("✗ 错误: 权限未被释放！")
    except sn_generator.FileAccessError:
        print("✓ 权限已正确释放（无法访问）")


if __name__ == '__main__':
    print("文件访问权限管理测试\n")
    
    test_without_permission()
    test_with_permission()
    test_nested_access()
    test_exception_safety()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

