#!/usr/bin/env python3
"""
序列号生成器 (SN Generator)
格式: 64YYWWXnnnnn
- 64: 固定前缀
- YY: 年份后两位
- WW: ISO周数 (01-53)
- X: 电脑编号 (1-9)
- nnnnn: 序列号 (00001-99999)
"""

import json
import os
import hashlib
import stat
import time
import subprocess
import platform
import uuid
import re
from datetime import datetime
from typing import Optional, Dict, List

# 尝试导入 fcntl（Unix/Linux 系统支持，Windows 不支持）
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

# 检测操作系统
IS_MACOS = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'
IS_WINDOWS = platform.system() == 'Windows'


class HashVerificationError(Exception):
    """日志文件哈希验证失败异常"""
    pass


class FileAccessError(Exception):
    """文件访问权限错误 - 需要先获取文件操作权限"""
    pass


class MacMappingError(Exception):
    """MAC地址映射错误 - MAC地址未在映射表中找到"""
    pass


# 全局状态：文件访问权限
_file_access_acquired = False
_file_lock = None
_file_lock_path = None
_file_lock_pid = None
_file_protected = False  # 文件是否被保护（不可变标志）


def _check_file_access():
    """
    检查是否已获取文件访问权限
    
    Raises:
        FileAccessError: 如果未获取权限
    """
    if not _file_access_acquired:
        raise FileAccessError(
            "❌ 错误: 未获取文件操作权限！\n"
            "   请使用以下方式获取权限：\n"
            "   with sn_generator.file_access():\n"
            "       # 你的代码\n"
            "       sn_generator.generate_sn()\n"
            "       sn_generator.update_sn_status(...)"
        )


def _acquire_file_lock(log_path: str = "all_sn_logs.json", timeout: float = 5.0) -> bool:
    """
    获取文件锁（用于防止并发写入）
    
    Args:
        log_path: 日志文件路径
        timeout: 超时时间（秒）
        
    Returns:
        bool: 是否成功获取锁
    """
    global _file_lock, _file_lock_path, _file_lock_pid
    
    if not HAS_FCNTL:
        # Windows 系统不支持 fcntl，使用简单的文件标记
        lock_path = log_path + '.lock'
        try:
            # 检查锁文件是否存在且进程是否存活
            if os.path.exists(lock_path):
                try:
                    with open(lock_path, 'r') as f:
                        lock_data = json.load(f)
                        lock_pid = lock_data.get('pid')
                        lock_time = lock_data.get('time', 0)
                        
                        # 检查进程是否存活（Windows 兼容方式）
                        try:
                            os.kill(lock_pid, 0)  # 检查进程是否存在
                            # 进程存在，检查是否超时（5分钟）
                            if time.time() - lock_time > 300:
                                # 超时，删除旧锁
                                os.remove(lock_path)
                            else:
                                # 锁被占用
                                return False
                        except (OSError, ProcessLookupError):
                            # 进程不存在，删除旧锁
                            os.remove(lock_path)
                except (json.JSONDecodeError, IOError):
                    # 锁文件损坏，删除
                    try:
                        os.remove(lock_path)
                    except:
                        pass
            
            # 创建新锁
            with open(lock_path, 'w') as f:
                json.dump({
                    'pid': os.getpid(),
                    'time': time.time()
                }, f)
            
            _file_lock_path = lock_path
            _file_lock_pid = os.getpid()
            return True
        except (IOError, OSError):
            return False
    
    # Unix/Linux 系统使用 fcntl
    lock_path = log_path + '.lock'
    
    try:
        # 检查并清理僵尸锁
        if os.path.exists(lock_path):
            try:
                with open(lock_path, 'r') as f:
                    lock_data = json.load(f)
                    lock_pid = lock_data.get('pid')
                    lock_time = lock_data.get('time', 0)
                    
                    # 检查进程是否存活
                    try:
                        os.kill(lock_pid, 0)
                        # 进程存在，检查是否超时（5分钟）
                        if time.time() - lock_time > 300:
                            # 超时，删除旧锁
                            os.remove(lock_path)
                        else:
                            # 锁被占用，尝试获取
                            pass
                    except (OSError, ProcessLookupError):
                        # 进程不存在，删除旧锁
                        os.remove(lock_path)
            except (json.JSONDecodeError, IOError):
                # 锁文件损坏，删除
                try:
                    os.remove(lock_path)
                except:
                    pass
        
        # 创建锁文件
        lock_file = open(lock_path, 'w+')  # 使用 w+ 模式，支持读写
        
        # 尝试获取排他锁（非阻塞）
        start_time = time.time()
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                # 成功获取锁，写入进程信息
                lock_file.seek(0)  # 回到文件开头
                lock_file.truncate()  # 清空文件
                json.dump({
                    'pid': os.getpid(),
                    'time': time.time()
                }, lock_file)
                lock_file.flush()
                
                _file_lock = lock_file
                _file_lock_path = lock_path
                _file_lock_pid = os.getpid()
                return True
            except BlockingIOError:
                # 锁被占用，等待一段时间后重试
                if (time.time() - start_time) > timeout:
                    lock_file.close()
                    try:
                        os.remove(lock_path)
                    except:
                        pass
                    return False
                time.sleep(0.1)
    except (IOError, OSError) as e:
        return False


def _set_file_immutable(file_path: str, immutable: bool = True) -> bool:
    """
    设置文件不可变标志（防止任何编辑器修改）
    
    Args:
        file_path: 文件路径
        immutable: True=设置为不可变，False=移除不可变标志
        
    Returns:
        bool: 是否设置成功
    """
    if not os.path.exists(file_path):
        return False
    
    try:
        if IS_MACOS:
            # macOS 使用 chflags
            # 优先尝试 schg（系统不可变标志，更强保护），如果失败则使用 uchg
            if immutable:
                # 先尝试 schg（需要 root，但提供更强保护）
                result_schg = subprocess.run(
                    ['chflags', 'schg', file_path],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result_schg.returncode == 0:
                    # schg 设置成功，验证
                    if _is_file_immutable(file_path):
                        return True
                
                # schg 失败或验证失败，使用 uchg
                flag = 'uchg'
            else:
                # 移除标志：先移除 schg，再移除 uchg
                flag = 'nouchg'
                # 先尝试移除 schg
                subprocess.run(['chflags', 'noschg', file_path], capture_output=True, timeout=5)
                # 移除不可变标志时，同时恢复写权限
                try:
                    os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                except (OSError, PermissionError):
                    pass  # 如果 chmod 失败，继续尝试移除标志
            
            result = subprocess.run(
                ['chflags', flag, file_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            # 如果移除标志成功，确保文件可写
            if not immutable and result.returncode == 0:
                try:
                    os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                except (OSError, PermissionError):
                    pass
            return result.returncode == 0
        elif IS_LINUX:
            # Linux 使用 chattr
            flag = '+i' if immutable else '-i'
            result = subprocess.run(
                ['chattr', flag, file_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            # 如果移除标志成功，确保文件可写
            if not immutable and result.returncode == 0:
                try:
                    os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                except (OSError, PermissionError):
                    pass
            return result.returncode == 0
        else:
            # Windows 或其他系统，只设置只读权限
            if immutable:
                os.chmod(file_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            else:
                os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            return True
    except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
        # chflags/chattr 可能不存在或需要 root 权限，降级为只读权限
        try:
            if immutable:
                os.chmod(file_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            else:
                os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            return True
        except (OSError, PermissionError):
            return False


def _is_file_immutable(file_path: str) -> bool:
    """
    检查文件是否设置了不可变标志
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否设置了不可变标志
    """
    if not os.path.exists(file_path):
        return False
    
    try:
        if IS_MACOS:
            # macOS 使用 ls -lO 检查标志
            result = subprocess.run(
                ['ls', '-lO', file_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return 'uchg' in result.stdout or 'schg' in result.stdout
        elif IS_LINUX:
            # Linux 使用 lsattr 检查标志
            result = subprocess.run(
                ['lsattr', file_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return 'i' in result.stdout.split()[0]
        else:
            # Windows 或其他系统，检查只读权限
            file_stat = os.stat(file_path)
            return not (file_stat.st_mode & stat.S_IWUSR)
    except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
        # 降级检查：检查只读权限
        try:
            file_stat = os.stat(file_path)
            return not (file_stat.st_mode & stat.S_IWUSR)
        except OSError:
            return False
    
    return False


def _release_file_lock():
    """
    释放文件锁
    """
    global _file_lock, _file_lock_path, _file_lock_pid
    
    if _file_lock_path and os.path.exists(_file_lock_path):
        try:
            if HAS_FCNTL and _file_lock:
                # Unix/Linux 系统
                fcntl.flock(_file_lock.fileno(), fcntl.LOCK_UN)
                _file_lock.close()
            
            # 删除锁文件
            os.remove(_file_lock_path)
        except (IOError, OSError):
            pass
    
    _file_lock = None
    _file_lock_path = None
    _file_lock_pid = None


class FileAccessManager:
    """
    文件访问权限管理器（上下文管理器）
    
    使用方式:
        with sn_generator.file_access():
            # 你的代码
            sn_generator.generate_sn()
            sn_generator.update_sn_status(...)
    """
    
    def __init__(self, log_path: str = "all_sn_logs.json"):
        """
        初始化文件访问管理器
        
        Args:
            log_path: 日志文件路径
        """
        self.log_path = log_path
        self.acquired = False
    
    def __enter__(self):
        """进入上下文，获取文件访问权限"""
        global _file_access_acquired, _file_protected
        
        if _file_access_acquired:
            # 已经获取权限，支持嵌套使用
            return self
        
        # 获取文件锁
        if not _acquire_file_lock(self.log_path):
            raise FileAccessError(
                "❌ 错误: 无法获取文件操作权限！\n"
                "   文件可能被其他进程占用，或锁文件已损坏。\n"
                "   请检查是否有其他程序正在使用 all_sn_logs.json 文件。"
            )
        
        # 临时移除文件保护（如果文件存在且被保护）
        if os.path.exists(self.log_path):
            # 检查是否设置了不可变标志
            is_immutable = _is_file_immutable(self.log_path)
            # 检查文件是否只读
            file_stat = os.stat(self.log_path)
            is_readonly = not (file_stat.st_mode & stat.S_IWUSR)
            
            # 如果文件被保护（不可变或只读），移除保护
            if is_immutable or is_readonly:
                _set_file_immutable(self.log_path, immutable=False)
                _file_protected = True  # 标记需要恢复保护
        
        _file_access_acquired = True
        self.acquired = True
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文，释放文件访问权限"""
        global _file_access_acquired, _file_protected
        
        if self.acquired:
            # 恢复文件保护
            # 只要是最外层调用（self.acquired=True），就恢复文件保护
            # 默认策略：文件应该被保护，除非用户明确取消保护（通过 --unprotect）
            if os.path.exists(self.log_path):
                # 检查是否有保护标记文件（表示文件应该被保护）
                protected_marker = self.log_path + '.protected'
                # 判断是否需要恢复保护：
                # 1. 如果有 .protected 标记文件，必须恢复保护
                # 2. 如果之前被保护过（_file_protected=True），也要恢复保护
                # 3. 如果都没有，也默认保护文件（创建标记文件并保护）
                should_protect = os.path.exists(protected_marker) or _file_protected or True
                
                if should_protect:
                    # 恢复文件保护
                    # 注意：如果文件在 OneDrive 等云同步目录中，同步服务可能会重置标志
                    # 因此需要多次尝试设置保护
                    max_retries = 3
                    for attempt in range(max_retries):
                        _set_file_immutable(self.log_path, immutable=True)
                        # 验证保护是否成功设置
                        if _is_file_immutable(self.log_path):
                            break
                        # 如果设置失败，等待一小段时间后重试（给同步服务时间）
                        if attempt < max_retries - 1:
                            import time
                            time.sleep(0.1)
                    
                    # 最终验证，如果还是失败，至少尝试设置只读权限
                    if not _is_file_immutable(self.log_path):
                        try:
                            import stat
                            os.chmod(self.log_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                        except:
                            pass
                    
                    # 创建或确保 .protected 标记文件存在（表示文件应该被保护）
                    if not os.path.exists(protected_marker):
                        try:
                            with open(protected_marker, 'w') as f:
                                f.write('This file indicates that all_sn_logs.json should be protected.\n')
                        except:
                            pass
                
                _file_protected = False
            
            _release_file_lock()
            _file_access_acquired = False
            self.acquired = False
        
        # 不抑制异常
        return False


def file_access(log_path: str = "all_sn_logs.json"):
    """
    获取文件访问权限（上下文管理器）
    
    使用方式:
        with sn_generator.file_access():
            # 你的代码
            sn_generator.generate_sn()
            sn_generator.update_sn_status(...)
    
    Args:
        log_path: 日志文件路径（默认: all_sn_logs.json）
        
    Returns:
        FileAccessManager: 文件访问管理器实例
    """
    return FileAccessManager(log_path)


def protect_file(log_path: str = "all_sn_logs.json") -> bool:
    """
    保护文件，防止任何编辑器直接修改
    
    设置文件为不可变（macOS/Linux）或只读（Windows），
    只有通过 sn_generator 模块的 file_access() 上下文管理器才能修改。
    
    Args:
        log_path: 日志文件路径
        
    Returns:
        bool: 是否保护成功
    """
    if not os.path.exists(log_path):
        print(f"⚠️  文件不存在: {log_path}")
        return False
    
    if _set_file_immutable(log_path, immutable=True):
        is_immutable = _is_file_immutable(log_path)
        if is_immutable:
            print(f"✓ 文件已保护: {log_path}")
            if IS_MACOS:
                # 检查是 schg 还是 uchg
                result = subprocess.run(
                    ['ls', '-lO', log_path],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if 'schg' in result.stdout:
                    print("  保护方式: chflags schg (系统不可变标志 - 最强保护)")
                else:
                    print("  保护方式: chflags uchg (用户不可变标志)")
                    print("  ⚠️  注意：在 OneDrive 目录中，uchg 可能被同步服务移除")
            elif IS_LINUX:
                print("  保护方式: chattr +i (不可变标志)")
            else:
                print("  保护方式: 只读权限")
            return True
        else:
            print(f"⚠️  文件保护设置可能失败（需要 root 权限）")
            print(f"   文件已设置为只读，但未设置不可变标志")
            return True
    else:
        print(f"✗ 文件保护失败: {log_path}")
        print(f"  提示: 某些系统可能需要 root 权限才能设置不可变标志")
        return False


def unprotect_file(log_path: str = "all_sn_logs.json") -> bool:
    """
    取消文件保护（仅用于紧急情况）
    
    Args:
        log_path: 日志文件路径
        
    Returns:
        bool: 是否取消保护成功
    """
    if not os.path.exists(log_path):
        return False
    
    if _set_file_immutable(log_path, immutable=False):
        # 删除保护标记文件
        protected_marker = log_path + '.protected'
        if os.path.exists(protected_marker):
            try:
                os.remove(protected_marker)
            except:
                pass
        
        print(f"✓ 文件保护已移除: {log_path}")
        return True
    else:
        print(f"✗ 取消文件保护失败: {log_path}")
        return False


def get_iso_week() -> tuple[str, str]:
    """
    获取当前年份后两位和ISO周数
    
    Returns:
        tuple: (YY, WW) 例如 ('24', '02')
    """
    now = datetime.now()
    # ISO周数：使用isocalendar()获取(year, week, weekday)
    year, week, _ = now.isocalendar()
    yy = str(year)[-2:]  # 年份后两位
    ww = f"{week:02d}"   # 周数，补零到2位
    return yy, ww


def normalize_mac_address(mac: str) -> str:
    """
    归一化MAC地址格式（统一为大写，使用冒号分隔）
    
    Args:
        mac: MAC地址字符串，支持多种格式（如 "AA:BB:CC:DD:EE:FF" 或 "AA-BB-CC-DD-EE-FF"）
        
    Returns:
        str: 归一化后的MAC地址（如 "AA:BB:CC:DD:EE:FF"）
        
    Raises:
        ValueError: 如果MAC地址格式无效
    """
    # 移除所有分隔符和空格，转换为大写
    mac_clean = re.sub(r'[:-]', '', mac.strip().upper())
    
    # 验证格式（必须是12位十六进制字符）
    if not re.match(r'^[0-9A-F]{12}$', mac_clean):
        raise ValueError(f"无效的MAC地址格式: {mac}")
    
    # 重新格式化为标准格式（用冒号分隔）
    return ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])


def get_host_mac_address(priority_interface: str = 'en0') -> Optional[str]:
    """
    获取本机MAC地址（优先获取指定网络接口的MAC地址）
    
    策略：
    1. 优先获取指定接口（默认en0，以太网）的MAC地址
    2. 如果指定接口不存在，尝试获取其他物理网络接口的MAC地址
    3. 排除虚拟接口（loopback、docker、vmware等）
    
    Args:
        priority_interface: 优先使用的网络接口名称（默认: 'en0'）
        
    Returns:
        str: MAC地址（格式: "AA:BB:CC:DD:EE:FF"），如果未找到则返回None
    """
    try:
        if IS_WINDOWS:
            # Windows系统：使用getnode()获取MAC地址
            mac_int = uuid.getnode()
            if mac_int != uuid.getnode():  # 检查是否有效
                mac_hex = f"{mac_int:012X}"
                return normalize_mac_address(mac_hex)
            return None
        else:
            # macOS/Linux系统：使用ifconfig或ip命令
            # 优先尝试获取指定接口的MAC地址
            try:
                if IS_MACOS:
                    # macOS: ifconfig en0 | grep ether
                    result = subprocess.run(
                        ['ifconfig', priority_interface],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        # 查找ether字段
                        match = re.search(r'ether\s+([0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2})', 
                                        result.stdout, re.IGNORECASE)
                        if match:
                            return normalize_mac_address(match.group(1))
                else:
                    # Linux: ip link show en0 | grep ether
                    result = subprocess.run(
                        ['ip', 'link', 'show', priority_interface],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        match = re.search(r'link/ether\s+([0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2})', 
                                        result.stdout, re.IGNORECASE)
                        if match:
                            return normalize_mac_address(match.group(1))
            except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
                pass
            
            # 如果指定接口未找到，尝试枚举所有网络接口
            try:
                if IS_MACOS:
                    # macOS: ifconfig | grep ether
                    result = subprocess.run(
                        ['ifconfig'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        # 查找所有ether字段，排除loopback
                        for line in result.stdout.split('\n'):
                            # 跳过loopback接口
                            if 'lo0' in line or 'loopback' in line.lower():
                                continue
                            match = re.search(r'ether\s+([0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2})', 
                                            line, re.IGNORECASE)
                            if match:
                                mac = normalize_mac_address(match.group(1))
                                # 排除全零MAC地址
                                if mac != '00:00:00:00:00:00':
                                    return mac
                else:
                    # Linux: ip link show | grep link/ether
                    result = subprocess.run(
                        ['ip', 'link', 'show'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            # 跳过loopback接口
                            if 'lo:' in line or 'loopback' in line.lower():
                                continue
                            match = re.search(r'link/ether\s+([0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2}[:-][0-9a-f]{2})', 
                                            line, re.IGNORECASE)
                            if match:
                                mac = normalize_mac_address(match.group(1))
                                # 排除全零MAC地址
                                if mac != '00:00:00:00:00:00':
                                    return mac
            except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
                pass
            
            # 最后尝试使用uuid.getnode()（跨平台方法）
            try:
                mac_int = uuid.getnode()
                if mac_int and mac_int != 0:
                    mac_hex = f"{mac_int:012X}"
                    mac = normalize_mac_address(mac_hex)
                    if mac != '00:00:00:00:00:00':
                        return mac
            except Exception:
                pass
            
            return None
    except Exception as e:
        print(f"警告: 获取MAC地址时发生错误: {e}")
        return None


def calculate_mac_mapping_hash(mac_mapping: Dict[str, int]) -> str:
    """
    计算MAC地址映射表的哈希值（用于验证数据完整性）
    
    Args:
        mac_mapping: MAC地址到computer_id的映射字典
        
    Returns:
        str: SHA256哈希值
    """
    # 将映射表转换为排序后的JSON字符串（确保一致性）
    # 按键（MAC地址）排序
    sorted_mapping = dict(sorted(mac_mapping.items()))
    mapping_json = json.dumps(sorted_mapping, sort_keys=True, ensure_ascii=False)
    
    # 计算SHA256哈希
    hash_obj = hashlib.sha256(mapping_json.encode('utf-8'))
    return hash_obj.hexdigest()


def load_mac_mapping(mapping_path: str = "mac_mapping.json", verify_hash: bool = True) -> Dict[str, int]:
    """
    加载MAC地址映射表（独立文件）
    
    Args:
        mapping_path: 映射表文件路径
        verify_hash: 是否验证哈希值（默认True）
        
    Returns:
        dict: MAC地址到computer_id的映射字典
        
    Raises:
        HashVerificationError: 当哈希验证失败时
    """
    if os.path.exists(mapping_path):
        try:
            with open(mapping_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 兼容旧格式（直接是字典）和新格式（包含hash的对象）
            if isinstance(data, dict):
                if 'mappings' in data:
                    # 新格式
                    mac_mapping = data['mappings']
                    stored_hash = data.get('_hash', '')
                    
                    # 验证哈希值
                    if verify_hash and stored_hash:
                        calculated_hash = calculate_mac_mapping_hash(mac_mapping)
                        if calculated_hash != stored_hash:
                            raise HashVerificationError(
                                f"❌ 错误: MAC映射表哈希验证失败！文件可能已被手动修改。\n"
                                f"   存储: {stored_hash[:16]}...\n"
                                f"   计算: {calculated_hash[:16]}...\n"
                                f"   为防止未授权的修改，已停止操作。\n"
                                f"   请使用 --register-mac 命令注册新的MAC地址。"
                            )
                    
                    return mac_mapping
                else:
                    # 旧格式（直接是映射字典），需要迁移
                    mac_mapping = data
                    # 自动保存为新格式
                    save_mac_mapping(mac_mapping, mapping_path)
                    return mac_mapping
            else:
                raise ValueError(f"MAC映射表文件格式不正确: {mapping_path}")
        except (json.JSONDecodeError, IOError) as e:
            raise ValueError(f"读取MAC映射表文件失败: {e}")
    else:
        # 文件不存在，返回空字典
        return {}


def save_mac_mapping(mac_mapping: Dict[str, int], mapping_path: str = "mac_mapping.json") -> bool:
    """
    保存MAC地址映射表到独立文件（自动更新哈希值）
    
    Args:
        mac_mapping: MAC地址到computer_id的映射字典
        mapping_path: 映射表文件路径
        
    Returns:
        bool: 是否保存成功
    """
    try:
        # 计算哈希值
        hash_value = calculate_mac_mapping_hash(mac_mapping)
        
        # 构建数据结构
        data = {
            '_hash': hash_value,
            '_hash_algorithm': 'SHA256',
            '_note': 'Do not modify this file manually. The _hash field is used to verify data integrity.',
            'mappings': mac_mapping
        }
        
        with open(mapping_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except IOError as e:
        print(f"错误: 保存MAC映射表文件失败: {e}")
        return False


def load_sn_config(config_path: str = "sn_config.json") -> dict:
    """
    加载序列号配置文件（本地状态，不包含MAC映射表）
    
    注意：MAC映射表已独立到 mac_mapping.json 文件中
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        dict: 配置信息，包含 current_week, sequence_number, last_generated_at, 
              last_generated_sn, status
              注意：computer_id不在配置文件中，必须从MAC映射表获取
    """
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
                # 确保所有必需的字段存在（注意：computer_id不在配置文件中，必须从MAC映射表获取）
                config.setdefault('current_week', '0000')
                config.setdefault('sequence_number', 0)
                config.setdefault('last_generated_at', None)
                config.setdefault('last_generated_sn', None)
                config.setdefault('status', 'pending')
                
                # 移除旧格式中的mac_mapping相关字段（如果存在）
                config.pop('mac_mapping', None)
                config.pop('_mac_mapping_hash', None)
                
                return config
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: 读取配置文件失败: {e}")
            # 返回默认配置
            return {
                'current_week': '0000', 
                'sequence_number': 0,
                'last_generated_at': None,
                'last_generated_sn': None,
                'status': 'pending'
            }
    else:
        # 如果文件不存在，创建默认配置（注意：computer_id不在配置文件中，必须从MAC映射表获取）
        default_config = {
            'current_week': '0000', 
            'sequence_number': 0,
            'last_generated_at': None,
            'last_generated_sn': None,
            'status': 'pending'
        }
        save_sn_config(default_config, config_path)
        return default_config


def save_sn_config(config: dict, config_path: str = "sn_config.json") -> bool:
    """
    保存序列号配置到文件（本地状态，不包含MAC映射表）
    
    注意：MAC映射表已独立到 mac_mapping.json 文件中
    
    Args:
        config: 配置信息
        config_path: 配置文件路径
        
    Returns:
        bool: 是否保存成功
    """
    try:
        # 移除mac_mapping相关字段（如果存在，确保不会保存）
        config_clean = {k: v for k, v in config.items() 
                       if k not in ['mac_mapping', '_mac_mapping_hash']}
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_clean, f, indent=2, ensure_ascii=False)
        return True
    except IOError as e:
        print(f"错误: 保存配置文件失败: {e}")
        return False


def get_computer_id_from_mac(mac_address: Optional[str] = None, 
                              mapping_path: str = "mac_mapping.json") -> int:
    """
    根据本机MAC地址从映射表中查找对应的computer_id
    
    Args:
        mac_address: MAC地址，如果为None则自动获取本机MAC地址
        mapping_path: MAC映射表文件路径
        
    Returns:
        int: computer_id (1-9)
        
    Raises:
        MacMappingError: 当MAC地址未在映射表中找到时
        HashVerificationError: 当MAC映射表哈希验证失败时
    """
    # 获取MAC地址
    if mac_address is None:
        mac_address = get_host_mac_address('en0')
        if mac_address is None:
            raise MacMappingError(
                "❌ 错误: 无法获取本机MAC地址。\n"
                "   请检查网络接口配置，或手动指定MAC地址。"
            )
    
    # 归一化MAC地址
    try:
        mac_normalized = normalize_mac_address(mac_address)
    except ValueError as e:
        raise MacMappingError(f"❌ 错误: 无效的MAC地址格式: {mac_address}")
    
    # 加载MAC映射表（会验证hash）
    mac_mapping = load_mac_mapping(mapping_path, verify_hash=True)
    
    # 查找映射
    if mac_normalized in mac_mapping:
        computer_id = mac_mapping[mac_normalized]
        # 验证computer_id范围
        if not (1 <= computer_id <= 9):
            raise MacMappingError(
                f"❌ 错误: 映射表中的computer_id无效: {computer_id} (必须在1-9之间)\n"
                f"   MAC地址: {mac_normalized}"
            )
        return computer_id
    else:
        # MAC地址未找到，报错
        raise MacMappingError(
            f"❌ 错误: 本机MAC地址 {mac_normalized} 未在映射表中找到。\n"
            f"   请联系管理员使用以下命令注册MAC地址：\n"
            f"   python sn_generator.py --register-mac {mac_normalized} --computer-id <ID>"
        )


def calculate_entry_hash(entry: dict) -> str:
    """
    计算单个日志条目的哈希值（基于sn, computer_id, week, generated_at, mac_address五个属性）
    
    Args:
        entry: 日志条目字典，必须包含 sn, computer_id, week, generated_at，可选包含 mac_address
        
    Returns:
        str: SHA256哈希值
    """
    # 使用这五个属性计算hash（mac_address如果没有则使用空字符串）
    hash_data = {
        'sn': entry.get('sn', ''),
        'computer_id': entry.get('computer_id', 0),
        'week': entry.get('week', ''),
        'generated_at': entry.get('generated_at', ''),
        'mac_address': entry.get('mac_address', '')
    }
    # 转换为JSON字符串（排序键以确保一致性）
    hash_json = json.dumps(hash_data, sort_keys=True, ensure_ascii=False)
    # 计算SHA256哈希
    hash_obj = hashlib.sha256(hash_json.encode('utf-8'))
    return hash_obj.hexdigest()


def calculate_logs_hash(logs: list) -> str:
    """
    计算日志列表的哈希值（用于验证数据完整性）
    注意：计算时排除每个条目的 _entry_hash 字段
    
    Args:
        logs: 日志列表
        
    Returns:
        str: SHA256哈希值
    """
    # 创建副本，排除 _entry_hash 字段用于计算整体hash
    logs_for_hash = []
    for entry in logs:
        entry_copy = {k: v for k, v in entry.items() if k != '_entry_hash'}
        logs_for_hash.append(entry_copy)
    
    # 将日志列表转换为JSON字符串（排序键以确保一致性）
    logs_json = json.dumps(logs_for_hash, sort_keys=True, ensure_ascii=False)
    # 计算SHA256哈希
    hash_obj = hashlib.sha256(logs_json.encode('utf-8'))
    return hash_obj.hexdigest()


def load_sn_logs(log_path: str = "all_sn_logs.json", verify_hash: bool = True, 
                 raise_on_error: bool = True) -> list:
    """
    加载所有序列号历史日志
    
    注意：此函数会自动获取文件访问权限，调用者无需手动使用 file_access()
    
    Args:
        log_path: 日志文件路径
        verify_hash: 是否验证哈希值（默认True）
        raise_on_error: 验证失败时是否抛出异常（默认True，用于防止重复序列号）
        
    Returns:
        list: 历史日志列表
        
    Raises:
        HashVerificationError: 当哈希验证失败且 raise_on_error=True 时
    """
    # 自动获取文件访问权限
    with file_access(log_path):
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # 兼容旧格式（直接是列表）和新格式（包含hash的对象）
                    if isinstance(data, list):
                        # 旧格式，直接返回
                        return data
                    elif isinstance(data, dict) and 'logs' in data:
                        # 新格式，包含hash
                        logs = data['logs']
                        stored_hash = data.get('_hash', '')
                        
                        # 验证每个条目的hash和整体hash
                        if verify_hash:
                            errors = []
                            
                            # 1. 验证每个条目的hash
                            for i, entry in enumerate(logs):
                                stored_entry_hash = entry.get('_entry_hash', '')
                                if stored_entry_hash:
                                    calculated_entry_hash = calculate_entry_hash(entry)
                                    if calculated_entry_hash != stored_entry_hash:
                                        errors.append(
                                            f"   条目 #{i+1} (SN: {entry.get('sn', 'N/A')}) 的hash验证失败\n"
                                            f"     存储: {stored_entry_hash[:16]}...\n"
                                            f"     计算: {calculated_entry_hash[:16]}..."
                                        )
                                else:
                                    # 旧条目可能没有_entry_hash，跳过验证
                                    pass
                            
                            # 2. 验证整体hash
                            if stored_hash:
                                calculated_hash = calculate_logs_hash(logs)
                                if calculated_hash != stored_hash:
                                    errors.append(
                                        f"   整体文件hash验证失败\n"
                                        f"     存储: {stored_hash[:16]}...\n"
                                        f"     计算: {calculated_hash[:16]}..."
                                    )
                            
                            # 如果有任何验证失败，处理错误
                            if errors:
                                error_msg = (
                                    f"❌ 错误: 日志文件哈希验证失败！文件可能已被手动修改。\n"
                                    + "\n".join(errors) + "\n"
                                    f"   为防止重复序列号，已停止生成。\n"
                                    f"   请使用 --verify 命令检查文件，或使用 --force 强制继续（不推荐）。"
                                )
                                if raise_on_error:
                                    raise HashVerificationError(error_msg)
                                else:
                                    print(f"⚠️  警告: {error_msg}")
                        
                        return logs
                    else:
                        print(f"警告: 日志文件格式不正确")
                        return []
            except (json.JSONDecodeError, IOError) as e:
                print(f"警告: 读取日志文件失败: {e}")
                return []
        else:
            return []


def save_sn_logs(logs: list, log_path: str = "all_sn_logs.json") -> bool:
    """
    保存序列号历史日志（包含哈希值用于验证）
    
    注意：此函数会自动获取文件访问权限，调用者无需手动使用 file_access()
    
    Args:
        logs: 日志列表
        log_path: 日志文件路径
        
    Returns:
        bool: 是否保存成功
    """
    # 自动获取文件访问权限
    with file_access(log_path):
        try:
            # 按 generated_at 从新到旧排序（最新的在最前面）
            logs_sorted = sorted(logs, key=lambda x: x.get('generated_at', ''), reverse=True)
            
            # 为每个条目计算并添加hash（使用新算法，包含mac_address）
            for entry in logs_sorted:
                # 总是重新计算hash，确保使用最新的算法（包含mac_address）
                entry['_entry_hash'] = calculate_entry_hash(entry)
            
            # 计算整体哈希值（排除_entry_hash字段）
            hash_value = calculate_logs_hash(logs_sorted)
            
            # 构建包含哈希的数据结构（元数据字段在前，logs 在后）
            data = {
                '_hash': hash_value,
                '_hash_algorithm': 'SHA256',
                '_entry_hash_fields': ['sn', 'computer_id', 'week', 'generated_at', 'mac_address'],
                '_note': 'Do not modify this file manually. Both _entry_hash and _hash fields are used to verify data integrity.',
                'logs': logs_sorted
            }
            
            with open(log_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"错误: 保存日志文件失败: {e}")
            return False


def add_sn_log(sn: str, computer_id: int, week: str, status: str = 'pending', 
               log_path: str = "all_sn_logs.json", force: bool = False) -> bool:
    """
    添加序列号到历史日志
    
    注意：此函数会自动获取文件访问权限，调用者无需手动使用 file_access()
    
    Args:
        sn: 序列号
        computer_id: 电脑编号
        week: 周数 (YYWW格式)
        status: 状态 (pending, occupied, failed)
        log_path: 日志文件路径
        force: 是否强制继续（即使hash验证失败）
        
    Returns:
        bool: 是否添加成功
        
    Raises:
        HashVerificationError: 当哈希验证失败且 force=False 时
    """
    # 自动获取文件访问权限
    with file_access(log_path):
        logs = load_sn_logs(log_path, raise_on_error=not force)
        
        # 创建新条目（只包含四个核心属性用于hash计算）
        generated_at = datetime.now().isoformat()
        log_entry = {
            'sn': sn,
            'computer_id': computer_id,
            'week': week,
            'generated_at': generated_at,
            'status': status
        }
        
        # 计算并添加条目hash
        log_entry['_entry_hash'] = calculate_entry_hash(log_entry)
        
        logs.append(log_entry)
        return save_sn_logs(logs, log_path)


def update_sn_status(sn: str, status: str, log_path: str = "all_sn_logs.json",
                    config_path: str = "sn_config.json", force: bool = False, 
                    mac_address: Optional[str] = None) -> bool:
    """
    更新序列号状态（用于被动接受其他模块返回的信息）
    
    注意：此函数会自动获取文件访问权限，调用者无需手动使用 file_access()
    
    注意：更新status字段不会影响_entry_hash，但如果更新mac_address会影响_entry_hash
    （因为_entry_hash基于sn, computer_id, week, generated_at, mac_address），
    会更新整体文件的_hash。
    
    Args:
        sn: 序列号
        status: 新状态 (pending, occupied, failed)
        log_path: 日志文件路径
        config_path: 配置文件路径
        force: 是否强制继续（即使hash验证失败）
        mac_address: MAC地址（可选），如果提供则更新到日志条目中
        
    Returns:
        bool: 是否更新成功
        
    Raises:
        HashVerificationError: 当哈希验证失败且 force=False 时
    """
    # 自动获取文件访问权限
    with file_access(log_path):
        # 更新日志文件中的状态（会先验证hash）
        try:
            logs = load_sn_logs(log_path, raise_on_error=not force)
        except HashVerificationError as e:
            if force:
                print(f"⚠️  警告: {str(e)}")
                logs = load_sn_logs(log_path, verify_hash=False, raise_on_error=False)
            else:
                raise
        
        updated = False
        
        for log_entry in logs:
            if log_entry.get('sn') == sn:
                log_entry['status'] = status
                log_entry['updated_at'] = datetime.now().isoformat()
                
                # 如果提供了MAC地址，更新它
                if mac_address is not None:
                    log_entry['mac_address'] = mac_address
                    # 由于mac_address影响_entry_hash，需要重新计算
                    log_entry['_entry_hash'] = calculate_entry_hash(log_entry)
                
                updated = True
                break
        
        if updated:
            if not save_sn_logs(logs, log_path):
                return False
        
        # 如果这是当前生成的序列号，也更新配置文件中的状态
        config = load_sn_config(config_path)
        if config.get('last_generated_sn') == sn:
            config['status'] = status
            save_sn_config(config, config_path)
        
        return updated


def verify_sn_logs(log_path: str = "all_sn_logs.json") -> tuple[bool, str]:
    """
    验证日志文件的哈希值（包括每个条目的hash和整体hash）
    
    注意：此函数会自动获取文件访问权限，调用者无需手动使用 file_access()
    
    Args:
        log_path: 日志文件路径
        
    Returns:
        tuple: (是否验证通过, 消息)
    """
    # 自动获取文件访问权限
    with file_access(log_path):
        if not os.path.exists(log_path):
            return False, "日志文件不存在"
        
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                return False, "日志文件使用旧格式，不包含哈希值"
            
            if not isinstance(data, dict) or 'logs' not in data:
                return False, "日志文件格式不正确"
            
            logs = data['logs']
            stored_hash = data.get('_hash', '')
            
            errors = []
            
            # 1. 验证每个条目的hash
            for i, entry in enumerate(logs):
                stored_entry_hash = entry.get('_entry_hash', '')
                if stored_entry_hash:
                    calculated_entry_hash = calculate_entry_hash(entry)
                    if calculated_entry_hash != stored_entry_hash:
                        errors.append(
                            f"   条目 #{i+1} (SN: {entry.get('sn', 'N/A')}) hash验证失败\n"
                            f"     存储: {stored_entry_hash[:16]}...\n"
                            f"     计算: {calculated_entry_hash[:16]}..."
                        )
                else:
                    errors.append(f"   条目 #{i+1} (SN: {entry.get('sn', 'N/A')}) 缺少_entry_hash字段")
            
            # 2. 验证整体hash
            if stored_hash:
                calculated_hash = calculate_logs_hash(logs)
                if calculated_hash != stored_hash:
                    errors.append(
                        f"   整体文件hash验证失败\n"
                        f"     存储: {stored_hash[:16]}...\n"
                        f"     计算: {calculated_hash[:16]}..."
                    )
            else:
                errors.append("   整体文件缺少_hash字段")
            
            if errors:
                return False, "✗ 哈希验证失败！文件可能已被修改。\n" + "\n".join(errors)
            else:
                return True, f"✓ 所有哈希验证通过 (整体hash: {stored_hash[:16]}..., 共{len(logs)}个条目)"
        
        except (json.JSONDecodeError, IOError) as e:
            return False, f"读取日志文件失败: {e}"


def generate_sn(computer_id: Optional[int] = None, config_path: str = "sn_config.json",
                log_path: str = "all_sn_logs.json", mapping_path: str = "mac_mapping.json",
                force: bool = False) -> str:
    """
    生成序列号
    
    格式: 64YYWWXnnnnn
    - 64: 固定前缀
    - YY: 年份后两位
    - WW: ISO周数 (01-53)
    - X: 电脑编号 (1-9) - 必须通过MAC地址映射表获取，禁止手动设置
    - nnnnn: 序列号 (00001-99999)
    
    注意：computer_id必须通过本机MAC地址从映射表中查找，不能手动指定。
    这确保了每个电脑的编号是硬编码的，无法随意修改。
    
    Args:
        computer_id: 已废弃，不再支持手动指定。必须通过MAC地址映射表自动获取。
        config_path: 配置文件路径
        log_path: 日志文件路径
        force: 是否强制继续（即使hash验证失败，不推荐使用）
        
    Returns:
        str: 生成的序列号
        
    Raises:
        ValueError: 如果序列号超过99999或电脑编号无效
        HashVerificationError: 当哈希验证失败且 force=False 时
        MacMappingError: 当本机MAC地址未在映射表中找到时
    """
    # 加载配置（会验证MAC映射表的hash）
    config = load_sn_config(config_path)
    
    # 强制通过MAC地址映射表获取computer_id（禁止手动设置）
    if computer_id is not None:
        raise ValueError(
            "❌ 错误: 不再支持手动指定computer_id。\n"
            "   computer_id必须通过本机MAC地址从映射表中自动获取。\n"
            "   请移除computer_id参数，程序会自动根据MAC地址查找。"
        )
    
    # 从MAC地址映射表获取computer_id（硬编码，确保绝对安全）
    try:
        computer_id = get_computer_id_from_mac(None, mapping_path)
    except MacMappingError as e:
        raise  # 直接抛出，不包装
    except HashVerificationError as e:
        if force:
            print(f"⚠️  警告: {str(e)}")
            # 强制模式下，跳过hash验证重新加载
            computer_id = get_computer_id_from_mac(None, mapping_path)
        else:
            raise
    
    # 验证电脑编号范围 (1-9) - 双重检查
    if not (1 <= computer_id <= 9):
        raise ValueError(f"电脑编号必须在1-9之间，当前值: {computer_id}")
    
    # 获取当前年份和周数
    yy, ww = get_iso_week()
    current_week = yy + ww  # 例如 "2402"
    
    # 检查周数是否变化
    stored_week = config.get('current_week', '0000')
    stored_sequence = config.get('sequence_number', 0)
    
    if current_week != stored_week:
        # 周数变化，重置序列号
        sequence_number = 1
        config['current_week'] = current_week
    elif stored_sequence == 0:
        # 同一周，但序列号为0（首次使用），从1开始
        sequence_number = 1
    else:
        # 同一周，递增序列号
        sequence_number = stored_sequence + 1
    
    # 检查序列号是否超过最大值
    if sequence_number > 99999:
        raise ValueError(f"序列号已超过最大值99999，当前周: {current_week}")
    
    # 更新配置（注意：不保存computer_id，确保绝对硬编码）
    config['sequence_number'] = sequence_number
    # 不保存computer_id到配置文件，确保每次都是从MAC映射表硬编码获取
    
    # 生成序列号
    sn = f"64{yy}{ww}{computer_id}{sequence_number:05d}"
    
    # 记录生成时间和序列号
    now = datetime.now()
    config['last_generated_at'] = now.isoformat()
    config['last_generated_sn'] = sn
    config['status'] = 'pending'  # 新生成的序列号默认为pending状态
    
    # 保存配置（不包含computer_id，确保硬编码）
    if not save_sn_config(config, config_path):
        print("警告: 配置保存失败，但序列号已生成")
    
    # 添加到历史日志（会验证hash，如果失败会抛出异常）
    # add_sn_log 会自动获取文件访问权限
    try:
        add_sn_log(sn, computer_id, current_week, status='pending', log_path=log_path, force=force)
    except HashVerificationError as e:
        # 如果hash验证失败，回滚序列号（不保存配置）
        config['sequence_number'] = stored_sequence
        save_sn_config(config, config_path)
        raise
    
    return sn


def get_current_status(config_path: str = "sn_config.json", mapping_path: str = "mac_mapping.json") -> dict:
    """
    获取当前序列号生成器状态
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        dict: 包含 computer_id, current_week, sequence_number, next_sn 等信息
        
    Raises:
        MacMappingError: 当本机MAC地址未在映射表中找到时
        HashVerificationError: 当MAC映射表哈希验证失败时
    """
    config = load_sn_config(config_path)
    yy, ww = get_iso_week()
    current_week = yy + ww
    
    # 从MAC地址映射表获取computer_id（硬编码，必须成功，不允许fallback）
    computer_id = get_computer_id_from_mac(None, mapping_path)
    
    status = {
        'computer_id': computer_id,
        'current_week': current_week,
        'stored_week': config.get('current_week', '0000'),
        'sequence_number': config.get('sequence_number', 0),
        'next_sequence': config.get('sequence_number', 0) + 1 if current_week == config.get('current_week', '0000') else 1
    }
    
    # 计算下一个序列号（不实际生成，只是预览）
    if status['next_sequence'] > 99999:
        status['next_sequence'] = None
        status['next_sn'] = None
        status['warning'] = "序列号已超过最大值99999"
    else:
        status['next_sn'] = f"64{yy}{ww}{status['computer_id']}{status['next_sequence']:05d}"
    
    return status


def set_computer_id(computer_id: int, config_path: str = "sn_config.json") -> bool:
    """
    设置电脑编号（已禁用）
    
    注意：此函数已被禁用。computer_id必须通过MAC地址映射表自动获取，
    禁止手动设置以确保硬编码安全。
    
    Args:
        computer_id: 电脑编号 (1-9) - 已废弃
        config_path: 配置文件路径
        
    Returns:
        bool: 总是返回False（函数已禁用）
        
    Raises:
        ValueError: 总是抛出异常，因为手动设置已被禁用
    """
    raise ValueError(
        "❌ 错误: 手动设置computer_id已被禁用。\n"
        "   computer_id必须通过本机MAC地址从映射表中自动获取。\n"
        "   请使用 --register-mac 命令注册新的MAC地址映射关系。"
    )


def register_mac_address(mac_address: str, computer_id: int, 
                         mapping_path: str = "mac_mapping.json") -> bool:
    """
    注册新的MAC地址到computer_id的映射关系
    
    Args:
        mac_address: MAC地址（支持多种格式）
        computer_id: 电脑编号 (1-9)
        config_path: 配置文件路径
        
    Returns:
        bool: 是否注册成功
        
    Raises:
        ValueError: 如果MAC地址格式无效或computer_id超出范围
    """
    # 验证computer_id范围
    if not (1 <= computer_id <= 9):
        raise ValueError(f"错误: computer_id必须在1-9之间，当前值: {computer_id}")
    
    # 归一化MAC地址
    try:
        mac_normalized = normalize_mac_address(mac_address)
    except ValueError as e:
        raise ValueError(f"错误: 无效的MAC地址格式: {mac_address}")
    
    # 加载MAC映射表（不验证hash，因为我们要修改它）
    mac_mapping = load_mac_mapping(mapping_path, verify_hash=False)
    
    # 检查MAC地址是否已存在
    if mac_normalized in mac_mapping:
        existing_id = mac_mapping[mac_normalized]
        if existing_id == computer_id:
            print(f"✓ MAC地址 {mac_normalized} 已存在，映射到 computer_id={computer_id}")
            return True
        else:
            raise ValueError(
                f"错误: MAC地址 {mac_normalized} 已存在，但映射到不同的computer_id: {existing_id}\n"
                f"   无法修改为 {computer_id}。如需修改，请先手动编辑配置文件。"
            )
    
    # 检查computer_id是否已被其他MAC使用
    for mac, cid in mac_mapping.items():
        if cid == computer_id:
            raise ValueError(
                f"错误: computer_id {computer_id} 已被MAC地址 {mac} 使用。\n"
                f"   每个computer_id只能映射到一个MAC地址。"
            )
    
    # 添加新映射
    mac_mapping[mac_normalized] = computer_id
    
    # 保存MAC映射表（会自动更新hash）
    if save_mac_mapping(mac_mapping, mapping_path):
        print(f"✓ MAC地址 {mac_normalized} 已成功注册，映射到 computer_id={computer_id}")
        print(f"  映射表hash已自动更新")
        return True
    else:
        print(f"✗ 保存MAC映射表失败")
        return False


def unregister_mac_address(mac_address: str, mapping_path: str = "mac_mapping.json") -> bool:
    """
    删除MAC地址映射关系
    
    Args:
        mac_address: MAC地址（支持多种格式）
        config_path: 配置文件路径
        
    Returns:
        bool: 是否删除成功
        
    Raises:
        ValueError: 如果MAC地址格式无效或未找到
    """
    # 归一化MAC地址
    try:
        mac_normalized = normalize_mac_address(mac_address)
    except ValueError as e:
        raise ValueError(f"错误: 无效的MAC地址格式: {mac_address}")
    
    # 加载MAC映射表（不验证hash，因为我们要修改它）
    mac_mapping = load_mac_mapping(mapping_path, verify_hash=False)
    
    # 检查MAC地址是否存在
    if mac_normalized not in mac_mapping:
        raise ValueError(f"错误: MAC地址 {mac_normalized} 未在映射表中找到")
    
    # 删除映射
    del mac_mapping[mac_normalized]
    
    # 保存MAC映射表（会自动更新hash）
    if save_mac_mapping(mac_mapping, mapping_path):
        print(f"✓ MAC地址 {mac_normalized} 已成功从映射表中删除")
        print(f"  映射表hash已自动更新")
        return True
    else:
        print(f"✗ 保存MAC映射表失败")
        return False


def reset_sequence(config_path: str = "sn_config.json") -> bool:
    """
    重置当前周的序列号（谨慎使用）
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        bool: 是否重置成功
    """
    config = load_sn_config(config_path)
    config['sequence_number'] = 0
    return save_sn_config(config, config_path)


def main():
    """命令行接口"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='序列号生成器 - 格式: 64YYWWXnnnnn',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 生成序列号（默认操作，自动根据MAC地址获取computer_id）
  python sn_generator.py
  
  # 显示当前状态
  python sn_generator.py --status
  
  # 注册新的MAC地址映射（管理员操作）
  python sn_generator.py --register-mac AA:BB:CC:DD:EE:01 --computer-id 1
  
  # 删除MAC地址映射（管理员操作）
  python sn_generator.py --unregister-mac AA:BB:CC:DD:EE:01
  
  # 更新序列号状态
  python sn_generator.py --update-status occupied --sn 642602100057 --mac 68:25:DD:AB:70:30
  
  # 验证文件完整性
  python sn_generator.py --verify
  
  # 保护文件（防止编辑器直接修改）
  python sn_generator.py --protect
  
  # 取消文件保护（紧急情况）
  python sn_generator.py --unprotect

重要说明:
  - computer_id必须通过MAC地址映射表自动获取，禁止手动设置
  - 使用 --register-mac 注册新的MAC地址映射关系
  - 映射表通过hash校验，防止未授权修改
        """
    )
    parser.add_argument('--generate', '-g', action='store_true', help='生成一个新的序列号（默认操作，自动根据MAC地址获取computer_id）')
    parser.add_argument('--status', '-s', action='store_true', help='显示当前状态（电脑编号、序列号、下一个SN等）')
    parser.add_argument('--register-mac', type=str, metavar='MAC', help='注册新的MAC地址映射（需配合--computer-id使用）')
    parser.add_argument('--unregister-mac', type=str, metavar='MAC', help='删除MAC地址映射（管理员操作）')
    parser.add_argument('--computer-id', type=int, metavar='ID', help='电脑编号 (1-9)，仅用于--register-mac命令')
    parser.add_argument('--reset', action='store_true', help='重置当前周的序列号（谨慎使用）')
    parser.add_argument('--update-status', type=str, metavar='STATUS', help='更新序列号状态: occupied/failed/pending（需配合--sn使用）')
    parser.add_argument('--sn', type=str, metavar='SN', help='要更新状态的序列号（需配合--update-status使用）')
    parser.add_argument('--mac', type=str, metavar='MAC', help='MAC地址（可选，配合--update-status使用）')
    parser.add_argument('--verify', action='store_true', help='验证日志文件的哈希值（检查文件是否被修改）')
    parser.add_argument('--force', action='store_true', help='强制继续（即使hash验证失败，不推荐使用）')
    parser.add_argument('--protect', action='store_true', help='保护文件，防止编辑器直接修改（设置不可变标志，macOS/Linux）')
    parser.add_argument('--unprotect', action='store_true', help='取消文件保护（仅用于紧急情况，允许编辑器直接修改）')
    parser.add_argument('--config', type=str, default='sn_config.json', help='配置文件路径 (默认: sn_config.json)')
    parser.add_argument('--mapping', type=str, default='mac_mapping.json', help='MAC映射表文件路径 (默认: mac_mapping.json)')
    parser.add_argument('--log', type=str, default='all_sn_logs.json', help='日志文件路径 (默认: all_sn_logs.json)')
    
    args = parser.parse_args()
    
    # 处理文件保护相关操作
    if args.protect:
        if protect_file(args.log):
            return 0
        else:
            return 1
    
    if args.unprotect:
        if unprotect_file(args.log):
            return 0
        else:
            return 1
    
    # 如果没有指定任何操作，默认生成序列号
    if not any([args.generate, args.status, args.register_mac is not None, args.unregister_mac is not None, args.reset, args.update_status, args.verify]):
        args.generate = True
    
    if args.unregister_mac is not None:
        try:
            if unregister_mac_address(args.unregister_mac, args.mapping):
                return 0
            else:
                return 1
        except ValueError as e:
            print(f"错误: {e}")
            return 1
        except Exception as e:
            print(f"错误: 删除MAC地址映射失败: {e}")
            return 1
    
    if args.register_mac is not None:
        if args.computer_id is None:
            print("错误: 使用 --register-mac 时必须指定 --computer-id")
            return 1
        try:
            if register_mac_address(args.register_mac, args.computer_id, args.mapping):
                return 0
            else:
                return 1
        except ValueError as e:
            print(f"错误: {e}")
            return 1
        except Exception as e:
            print(f"错误: 注册MAC地址失败: {e}")
            return 1
    
    if args.verify:
        # verify_sn_logs() 会自动获取文件访问权限
        try:
            is_valid, message = verify_sn_logs(args.log)
            print(message)
            return 0 if is_valid else 1
        except FileAccessError as e:
            print(f"错误: {e}")
            return 1
    
    if args.update_status:
        if not args.sn:
            print("错误: 使用 --update-status 时必须指定 --sn")
            return 1
        valid_statuses = ['pending', 'occupied', 'failed']
        if args.update_status not in valid_statuses:
            print(f"错误: 状态必须是以下之一: {', '.join(valid_statuses)}")
            return 1
        # update_sn_status() 会自动获取文件访问权限
        if update_sn_status(args.sn, args.update_status, args.log, args.config, mac_address=args.mac):
            mac_info = f" (MAC: {args.mac})" if args.mac else ""
            print(f"✓ 序列号 {args.sn} 状态已更新为: {args.update_status}{mac_info}")
        else:
            print(f"✗ 更新序列号状态失败（未找到序列号: {args.sn}）")
        return
    
    if args.reset:
        if reset_sequence(args.config):
            print("✓ 序列号已重置")
        else:
            print("✗ 重置序列号失败")
        return
    
    if args.status:
        status = get_current_status(args.config, args.mapping)
        config = load_sn_config(args.config)
        print("\n序列号生成器状态:")
        print(f"  电脑编号: {status['computer_id']}")
        print(f"  当前周: {status['current_week']} (存储: {status['stored_week']})")
        print(f"  当前序列号: {status['sequence_number']}")
        print(f"  下一个序列号: {status['next_sequence']}")
        if status.get('next_sn'):
            print(f"  下一个SN: {status['next_sn']}")
        if config.get('last_generated_sn'):
            print(f"  最后生成的SN: {config['last_generated_sn']}")
            print(f"  生成时间: {config.get('last_generated_at', 'N/A')}")
            print(f"  状态: {config.get('status', 'N/A')}")
        if status.get('warning'):
            print(f"  警告: {status['warning']}")
        print()
        return
    
    if args.generate:
        # generate_sn() 会自动获取文件访问权限
        try:
            sn = generate_sn(config_path=args.config, log_path=args.log, mapping_path=args.mapping, force=args.force)
            print(sn)
        except HashVerificationError as e:
            print(str(e))
            return 1
        except ValueError as e:
            print(f"错误: {e}")
            return 1
        except FileAccessError as e:
            print(f"错误: {e}")
            return 1
        except Exception as e:
            print(f"错误: 生成序列号失败: {e}")
            return 1


if __name__ == '__main__':
    exit(main() or 0)

