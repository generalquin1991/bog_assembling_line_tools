#!/usr/bin/env python3
"""
声音播放工具函数
用于在需要用户操作和测试完成时播放提示音
"""

import platform
import subprocess
import threading


def _play_notification_sound_sync():
    """同步播放通知提示音（内部函数）"""
    system = platform.system()
    
    if system == 'Darwin':  # macOS
        try:
            subprocess.run(['afplay', '/System/Library/Sounds/Ping.aiff'], 
                         check=True, stderr=subprocess.DEVNULL, timeout=2)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            # 静默失败，不打印错误信息
            return False
    elif system == 'Windows':
        try:
            import winsound
            winsound.Beep(1000, 300)  # 频率 1000Hz，持续时间 300ms
            return True
        except Exception:
            return False
    elif system == 'Linux':
        try:
            subprocess.run(['paplay', '/usr/share/sounds/freedesktop/stereo/message.oga'], 
                         check=True, stderr=subprocess.DEVNULL, timeout=2)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
    return False


def play_notification_sound(background=True):
    """
    播放通知提示音（简短）- 使用 Ping.aiff
    用于需要用户操作时（如按按键）
    
    Args:
        background: 是否在后台线程中播放（默认True，不阻塞主线程）
    """
    if background:
        # 在后台线程中播放，不阻塞主线程
        thread = threading.Thread(target=_play_notification_sound_sync, daemon=True)
        thread.start()
        return True
    else:
        # 同步播放
        return _play_notification_sound_sync()


def _play_completion_sound_sync():
    """同步播放完成提示音（内部函数）"""
    system = platform.system()
    
    if system == 'Darwin':  # macOS
        try:
            # 播放两次 Ping.aiff，间隔 0.3 秒
            subprocess.run(['afplay', '/System/Library/Sounds/Ping.aiff'], 
                         check=True, stderr=subprocess.DEVNULL, timeout=2)
            import time
            time.sleep(0.3)
            subprocess.run(['afplay', '/System/Library/Sounds/Ping.aiff'], 
                         check=True, stderr=subprocess.DEVNULL, timeout=2)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
    elif system == 'Windows':
        try:
            import winsound
            winsound.Beep(800, 300)
            import time
            time.sleep(0.2)
            winsound.Beep(1000, 500)
            return True
        except Exception:
            return False
    elif system == 'Linux':
        try:
            subprocess.run(['paplay', '/usr/share/sounds/freedesktop/stereo/complete.oga'], 
                         check=True, stderr=subprocess.DEVNULL, timeout=2)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
    return False


def play_completion_sound(background=True):
    """
    播放完成提示音（较长）- 使用 Ping.aiff 播放两次
    用于测试完成时
    
    Args:
        background: 是否在后台线程中播放（默认True，不阻塞主线程）
    """
    if background:
        # 在后台线程中播放，不阻塞主线程
        thread = threading.Thread(target=_play_completion_sound_sync, daemon=True)
        thread.start()
        return True
    else:
        # 同步播放
        return _play_completion_sound_sync()


if __name__ == "__main__":
    # 简单测试
    print("测试通知提示音...")
    play_notification_sound()
    
    import time
    time.sleep(1)
    
    print("测试完成提示音...")
    play_completion_sound()

