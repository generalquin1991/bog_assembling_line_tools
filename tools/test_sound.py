#!/usr/bin/env python3
"""
声音播放测试脚本
用于测试不同平台的声音播放功能
"""

import platform
import subprocess
import sys


def play_sound_macos(sound_file=None):
    """在 macOS 上播放声音"""
    if sound_file:
        # 播放指定的声音文件
        try:
            subprocess.run(['afplay', sound_file], check=True)
            print(f"✓ 播放声音文件: {sound_file}")
        except subprocess.CalledProcessError:
            print(f"✗ 无法播放声音文件: {sound_file}")
    else:
        # 播放系统提示音 - 使用 Ping.aiff
        try:
            subprocess.run(['afplay', '/System/Library/Sounds/Ping.aiff'], 
                         check=True, stderr=subprocess.DEVNULL)
            print("✓ 播放系统提示音 (Ping.aiff)")
        except (subprocess.CalledProcessError, FileNotFoundError):
            # 如果系统声音文件不存在，使用 say 命令
            try:
                subprocess.run(['say', '提示音'], check=True, stderr=subprocess.DEVNULL)
                print("✓ 使用 say 命令播放提示音")
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("✗ 无法播放声音")


def play_sound_windows(sound_file=None):
    """在 Windows 上播放声音"""
    import winsound
    
    if sound_file:
        try:
            winsound.PlaySound(sound_file, winsound.SND_FILENAME)
            print(f"✓ 播放声音文件: {sound_file}")
        except Exception as e:
            print(f"✗ 无法播放声音文件: {sound_file}, 错误: {e}")
    else:
        # 播放系统提示音
        try:
            winsound.Beep(1000, 500)  # 频率 1000Hz，持续时间 500ms
            print("✓ 播放系统提示音 (Beep)")
        except Exception as e:
            print(f"✗ 无法播放声音, 错误: {e}")


def play_sound_linux(sound_file=None):
    """在 Linux 上播放声音"""
    if sound_file:
        # 尝试使用 aplay
        try:
            subprocess.run(['aplay', sound_file], check=True)
            print(f"✓ 播放声音文件: {sound_file} (使用 aplay)")
        except (subprocess.CalledProcessError, FileNotFoundError):
            # 尝试使用 paplay
            try:
                subprocess.run(['paplay', sound_file], check=True)
                print(f"✓ 播放声音文件: {sound_file} (使用 paplay)")
            except (subprocess.CalledProcessError, FileNotFoundError):
                print(f"✗ 无法播放声音文件: {sound_file}")
    else:
        # 播放系统提示音（需要系统声音文件）
        try:
            subprocess.run(['paplay', '/usr/share/sounds/freedesktop/stereo/message.oga'], check=True)
            print("✓ 播放系统提示音")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("✗ 无法播放系统提示音")


def play_sound(sound_file=None):
    """
    跨平台播放声音
    
    Args:
        sound_file: 可选的声音文件路径。如果为 None，播放系统提示音
    """
    system = platform.system()
    
    print(f"检测到系统: {system}")
    print("正在播放声音...")
    
    if system == 'Darwin':  # macOS
        play_sound_macos(sound_file)
    elif system == 'Windows':
        play_sound_windows(sound_file)
    elif system == 'Linux':
        play_sound_linux(sound_file)
    else:
        print(f"✗ 不支持的系统: {system}")


def play_notification_sound():
    """播放通知提示音（简短）- 使用 Ping.aiff"""
    system = platform.system()
    if system == 'Darwin':
        try:
            subprocess.run(['afplay', '/System/Library/Sounds/Ping.aiff'], 
                         check=True, stderr=subprocess.DEVNULL)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    else:
        play_sound()
        return True


def play_completion_sound():
    """播放完成提示音（较长）- 使用 Ping.aiff 播放两次"""
    system = platform.system()
    
    if system == 'Darwin':  # macOS
        # 播放两次提示音表示完成
        try:
            subprocess.run(['afplay', '/System/Library/Sounds/Ping.aiff'], 
                         check=True, stderr=subprocess.DEVNULL)
            import time
            time.sleep(0.3)
            subprocess.run(['afplay', '/System/Library/Sounds/Ping.aiff'], 
                         check=True, stderr=subprocess.DEVNULL)
            print("✓ 播放完成提示音 (Ping.aiff x2)")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                subprocess.run(['say', '测试完成'], check=True, stderr=subprocess.DEVNULL)
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("✗ 无法播放完成提示音")
                return False
    elif system == 'Windows':
        import winsound
        try:
            winsound.Beep(800, 300)
            import time
            time.sleep(0.2)
            winsound.Beep(1000, 500)
            print("✓ 播放完成提示音")
        except Exception as e:
            print(f"✗ 无法播放完成提示音: {e}")
    elif system == 'Linux':
        try:
            subprocess.run(['paplay', '/usr/share/sounds/freedesktop/stereo/complete.oga'], check=True)
            print("✓ 播放完成提示音")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("✗ 无法播放完成提示音")


if __name__ == "__main__":
    print("=" * 60)
    print("声音播放测试")
    print("=" * 60)
    print()
    
    # 测试 1: 播放系统提示音
    print("测试 1: 播放系统提示音")
    play_notification_sound()
    print()
    
    # 等待用户输入
    input("按 Enter 继续测试完成提示音...")
    print()
    
    # 测试 2: 播放完成提示音
    print("测试 2: 播放完成提示音")
    play_completion_sound()
    print()
    
    # 测试 3: 如果提供了声音文件路径，播放自定义声音
    if len(sys.argv) > 1:
        sound_file = sys.argv[1]
        print(f"测试 3: 播放自定义声音文件: {sound_file}")
        play_sound(sound_file)
        print()
    
    print("=" * 60)
    print("测试完成")
    print("=" * 60)

