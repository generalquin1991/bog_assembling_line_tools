#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESP自动烧录工具
支持ESP32/ESP8266自动烧录固件
"""

import json
import os
import sys
import argparse
import subprocess
import shutil
import serial.tools.list_ports
import serial
import csv
import threading
import time
import re
from datetime import datetime
from pathlib import Path

try:
    import inquirer
except ImportError:
    inquirer = None


class RestartTUI(Exception):
    """用于重启TUI的异常"""
    pass


class SerialMonitor:
    """串口监听器，用于监听设备日志并自动输入"""
    
    def __init__(self, port, baud_rate=115200):
        self.port = port
        self.baud_rate = baud_rate
        self.serial_conn = None
        self.running = False
        self.buffer = ""
        self.device_info = {
            'mac_address': None,
            'hw_rev': None,
            'sn': None,
            'version': None,
            'device_code': None
        }
        self.waiting_for_input = None
        self.input_value = None
        self.input_sent = False
        self.monitor_thread = None
        
    def open(self):
        """打开串口连接"""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=1,
                write_timeout=1
            )
            time.sleep(0.5)  # 等待串口稳定
            return True
        except Exception as e:
            print(f"Error: Unable to open serial port {self.port}: {e}")
            return False
    
    def close(self):
        """关闭串口连接"""
        self.running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
    
    def send_command(self, command):
        """发送命令到串口"""
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.write((command + '\n').encode('utf-8'))
                self.serial_conn.flush()
                return True
            except Exception as e:
                print(f"Error: Failed to send command: {e}")
                return False
        return False
    
    def extract_device_info(self, line):
        """从日志行中提取设备信息"""
        # 提取MAC地址
        mac_pattern = r'MAC[:\s]+([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})'
        mac_match = re.search(mac_pattern, line, re.IGNORECASE)
        if mac_match:
            self.device_info['mac_address'] = mac_match.group(0).split(':')[-1].strip() if ':' in mac_match.group(0) else mac_match.group(0)
        
        # 提取HW版本
        hw_pattern = r'HW[_\s]*[Rr]ev[:\s]*([A-Za-z0-9._-]+)'
        hw_match = re.search(hw_pattern, line, re.IGNORECASE)
        if hw_match:
            self.device_info['hw_rev'] = hw_match.group(1)
        
        # 提取SN
        sn_pattern = r'SN[:\s]*([A-Za-z0-9._-]+)'
        sn_match = re.search(sn_pattern, line, re.IGNORECASE)
        if sn_match:
            self.device_info['sn'] = sn_match.group(1)
        
        # 提取版本号
        version_pattern = r'[Vv]ersion[:\s]*([0-9.]+)'
        version_match = re.search(version_pattern, line)
        if version_match:
            self.device_info['version'] = version_match.group(1)
    
    def check_input_prompt(self, line):
        """检查是否需要输入"""
        line_lower = line.lower()
        
        # 检查是否需要输入版本号
        if any(keyword in line_lower for keyword in ['version', '版本', '请输入版本', 'enter version']):
            if '?' in line or ':' in line:
                return 'version'
        
        # 检查是否需要输入设备号
        if any(keyword in line_lower for keyword in ['device', '设备', 'sn', 'serial', '请输入设备', 'enter device']):
            if '?' in line or ':' in line:
                return 'device_code'
        
        return None
    
    def check_confirmation(self, line, input_type, value):
        """检查确认信息"""
        line_lower = line.lower()
        value_lower = str(value).lower()
        
        if input_type == 'version':
            # 检查版本号是否被确认
            if value_lower in line_lower or f"version: {value}" in line_lower:
                return True
        elif input_type == 'device_code':
            # 检查设备号是否被确认
            if value_lower in line_lower or f"device: {value}" in line_lower or f"sn: {value}" in line_lower:
                return True
        
        return False
    
    def monitor_loop(self, version_string, device_code_rule):
        """监听循环"""
        if not self.serial_conn or not self.serial_conn.is_open:
            return
        
        self.running = True
        timeout = time.time() + 120  # 2分钟超时
        
        while self.running and time.time() < timeout:
            try:
                if self.serial_conn.in_waiting > 0:
                    data = self.serial_conn.read(self.serial_conn.in_waiting)
                    text = data.decode('utf-8', errors='ignore')
                    self.buffer += text
                    
                    # 按行处理
                    while '\n' in self.buffer:
                        line, self.buffer = self.buffer.split('\n', 1)
                        line = line.strip()
                        if line:
                            print(f"[Device Log] {line}")
                            
                            # Extract device information
                            self.extract_device_info(line)
                            
                            # Check if input is needed
                            if not self.waiting_for_input and not self.input_sent:
                                prompt_type = self.check_input_prompt(line)
                                if prompt_type == 'version' and version_string:
                                    self.waiting_for_input = 'version'
                                    self.input_value = version_string
                                    time.sleep(0.5)  # Wait for prompt to fully display
                                    self.send_command(version_string)
                                    self.input_sent = True
                                    print(f"[Auto Input] Version: {version_string}")
                                elif prompt_type == 'device_code' and device_code_rule:
                                    self.waiting_for_input = 'device_code'
                                    # Generate device code according to rule
                                    device_code = self.generate_device_code(device_code_rule)
                                    self.input_value = device_code
                                    time.sleep(0.5)
                                    self.send_command(device_code)
                                    self.input_sent = True
                                    print(f"[Auto Input] Device Code: {device_code}")
                            
                            # Check confirmation
                            if self.waiting_for_input and self.input_sent:
                                if self.check_confirmation(line, self.waiting_for_input, self.input_value):
                                    print(f"[Confirmed] {self.waiting_for_input} confirmed: {self.input_value}")
                                    if self.waiting_for_input == 'version':
                                        self.device_info['version'] = self.input_value
                                    elif self.waiting_for_input == 'device_code':
                                        self.device_info['device_code'] = self.input_value
                                    self.waiting_for_input = None
                                    self.input_sent = False
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"Monitoring error: {e}")
                break
    
    def generate_device_code(self, rule):
        """根据规则生成设备号"""
        if rule == 'SN: YYMMDD+序号':
            # 生成格式: SN240101001
            now = datetime.now()
            date_str = now.strftime('%y%m%d')
            # 简单序号（实际应该从文件或数据库获取）
            seq = '001'
            return f"SN{date_str}{seq}"
        elif rule == 'MAC后6位':
            # 使用MAC地址后6位
            if self.device_info.get('mac_address'):
                mac = self.device_info['mac_address'].replace(':', '').replace('-', '')
                return mac[-6:].upper()
            return 'UNKNOWN'
        else:
            # 自定义规则或默认
            return rule
    
    def start_monitoring(self, version_string, device_code_rule):
        """启动监听线程"""
        self.monitor_thread = threading.Thread(
            target=self.monitor_loop,
            args=(version_string, device_code_rule),
            daemon=True
        )
        self.monitor_thread.start()
    
    def wait_for_completion(self, timeout=120):
        """等待监听完成"""
        if self.monitor_thread:
            self.monitor_thread.join(timeout=timeout)
    
    def get_device_info(self):
        """获取设备信息"""
        return self.device_info.copy()


def check_port_exists(port):
    """检查串口是否存在"""
    return os.path.exists(port)


def filter_serial_ports(ports, config=None):
    """过滤串口列表，排除非串口设备
    
    Args:
        ports: serial.tools.list_ports.comports() 返回的端口列表
        config: 配置字典，包含过滤规则
    
    Returns:
        过滤后的端口列表
    """
    if not config or not config.get('filter_serial_ports', False):
        return ports
    
    filtered_ports = []
    serial_keywords = config.get('serial_port_keywords', ['USB Serial', 'Serial', 'COM', 'USB'])
    exclude_patterns = config.get('exclude_port_patterns', ['debug-console', 'wlan-debug', 'Bluetooth', 'HUAWEI', 'n/a'])
    
    for port in ports:
        device_lower = port.device.lower()
        description_lower = (port.description or '').lower()
        
        # 检查是否匹配排除模式
        should_exclude = False
        for pattern in exclude_patterns:
            if pattern.lower() in device_lower or pattern.lower() in description_lower:
                should_exclude = True
                break
        
        if should_exclude:
            continue
        
        # 检查是否匹配串口关键词（如果有关键词配置）
        if serial_keywords:
            is_serial = False
            for keyword in serial_keywords:
                if keyword.lower() in description_lower:
                    is_serial = True
                    break
            
            # 如果有关键词配置但没有匹配到，且描述不是 "n/a"，也排除
            if not is_serial and description_lower != 'n/a':
                continue
        
        filtered_ports.append(port)
    
    return filtered_ports


def detect_esp_device(port, baud_rate=115200):
    """检测ESP设备是否连接（仅在必要时使用，会占用串口）"""
    ser = None
    try:
        ser = serial.Serial(port, baud_rate, timeout=2)
        time.sleep(0.5)
        
        # 尝试发送AT命令或检测芯片
        ser.write(b'\r\n')
        time.sleep(0.5)
        
        if ser.in_waiting > 0:
            response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
            # 检查是否有ESP相关的响应
            if any(keyword in response.upper() for keyword in ['ESP', 'READY', 'OK']):
                return True
        
        return False
    except Exception as e:
        print(f"检测设备时出错: {e}")
        return False
    finally:
        # 确保串口总是被关闭
        if ser and ser.is_open:
            ser.close()


def save_to_csv(device_info, csv_file='device_records.csv'):
    """保存设备信息到CSV文件"""
    file_exists = os.path.exists(csv_file)
    
    try:
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            fieldnames = ['timestamp', 'mac_address', 'hw_rev', 'sn', 'version', 'device_code']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
            
            record = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'mac_address': device_info.get('mac_address', ''),
                'hw_rev': device_info.get('hw_rev', ''),
                'sn': device_info.get('sn', ''),
                'version': device_info.get('version', ''),
                'device_code': device_info.get('device_code', '')
            }
            
            writer.writerow(record)
            print(f"\n✓ 设备信息已保存到 {csv_file}")
            return True
    except Exception as e:
        print(f"错误: 保存CSV失败: {e}")
        return False


class ESPFlasher:
    """ESP烧录器类"""
    
    def __init__(self, config_path="config.json"):
        """初始化烧录器，加载配置"""
        self.config_path = config_path
        self.config = self.load_config()
        self.validate_config()
    
    def load_config(self):
        """加载配置文件，如果波特率字段缺失则从config.json读取默认值"""
        if not os.path.exists(self.config_path):
            print(f"错误: 配置文件 {self.config_path} 不存在")
            sys.exit(1)
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 如果是dev或factory配置文件，且缺少波特率字段，从config.json读取默认值
            if self.config_path in ['config_develop.json', 'config_factory.json']:
                base_config_path = 'config.json'
                if os.path.exists(base_config_path):
                    try:
                        with open(base_config_path, 'r', encoding='utf-8') as f:
                            base_config = json.load(f)
                        
                        # 需要从config.json读取默认值的字段：波特率相关字段、hash校验超时、串口过滤配置
                        default_fields = ['baud_rate', 'monitor_baud', 'hash_verification_timeout',
                                         'filter_serial_ports', 'serial_port_keywords', 'exclude_port_patterns']
                        for field in default_fields:
                            if field not in config and field in base_config:
                                config[field] = base_config[field]
                    except Exception as e:
                        # 如果读取config.json失败，忽略错误，继续使用当前配置
                        pass
            
            return config
        except json.JSONDecodeError as e:
            print(f"错误: 配置文件格式错误: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"错误: 读取配置文件失败: {e}")
            sys.exit(1)
    
    def validate_config(self):
        """验证配置参数"""
        required_fields = ['serial_port', 'baud_rate', 'chip_type', 'firmware_path']
        for field in required_fields:
            if field not in self.config:
                print(f"错误: 配置文件中缺少必需字段: {field}")
                sys.exit(1)
        
        # 检查固件文件是否存在
        firmware_path = self.config['firmware_path']
        if not os.path.exists(firmware_path):
            print(f"错误: 固件文件不存在: {firmware_path}")
            print("请将固件文件放置在firmware文件夹中")
            sys.exit(1)
    
    def check_esptool(self):
        """检查esptool是否可用"""
        # 优先使用 'esptool'（新版本），如果找不到再回退到 'esptool.py'（向后兼容）
        esptool_path = shutil.which('esptool') or shutil.which('esptool.py')
        if not esptool_path:
            print("错误: 未找到esptool，请运行: pip install esptool")
            sys.exit(1)
        return esptool_path
    
    def list_ports(self):
        """列出所有可用的串口（根据配置过滤非串口设备）"""
        ports = serial.tools.list_ports.comports()
        if not ports:
            print("未找到可用的串口设备")
            return []
        
        # 根据配置过滤非串口设备
        ports = filter_serial_ports(ports, self.config)
        
        if not ports:
            print("未找到可用的串口设备（已过滤非串口设备）")
            return []
        
        print("\n可用的串口设备:")
        print("-" * 60)
        for i, port in enumerate(ports, 1):
            print(f"{i}. {port.device} - {port.description}")
        print("-" * 60)
        return [port.device for port in ports]
    
    def is_combined_firmware(self, firmware_path):
        """检测是否为combined固件（包含bootloader和分区表）
        通常从0x0地址开始烧录
        """
        filename = os.path.basename(firmware_path).lower()
        # 检测常见的combined固件命名模式
        combined_keywords = [
            'combined', 'full', 'complete', 
            'all_in_one', 'all-in-one', 'allinone',
            'factory', 'single', 'monolithic'
        ]
        return any(keyword in filename for keyword in combined_keywords)
    
    def get_chip_defaults(self, chip_type):
        """根据芯片类型获取默认的Flash参数"""
        chip_type_lower = chip_type.lower()
        
        # ESP32-C2 的默认参数
        if 'esp32c2' in chip_type_lower or 'esp32-c2' in chip_type_lower:
            return {
                'flash_freq': '60m',  # ESP32-C2 支持: 60m, 30m, 20m, 15m (不支持 40m)
                'flash_size': '2MB',  # 大多数 ESP32-C2 是 2MB
                'flash_mode': 'dio'
            }
        # ESP32 的默认参数
        elif 'esp32' in chip_type_lower and 'c2' not in chip_type_lower and 'c3' not in chip_type_lower and 'c6' not in chip_type_lower and 's2' not in chip_type_lower and 's3' not in chip_type_lower:
            return {
                'flash_freq': '40m',
                'flash_size': '4MB',
                'flash_mode': 'dio'
            }
        # ESP32-C3 的默认参数
        elif 'esp32c3' in chip_type_lower or 'esp32-c3' in chip_type_lower:
            return {
                'flash_freq': '80m',
                'flash_size': '4MB',
                'flash_mode': 'dio'
            }
        # 其他芯片类型的默认值
        else:
            return {
                'flash_freq': '40m',
                'flash_size': '4MB',
                'flash_mode': 'dio'
            }
    
    def adjust_flash_params(self):
        """根据芯片类型自动调整Flash参数"""
        chip_type = self.config.get('chip_type', 'esp32')
        defaults = self.get_chip_defaults(chip_type)
        
        # 如果配置中的参数可能不兼容，使用默认值
        current_freq = self.config.get('flash_freq', '40m')
        current_size = self.config.get('flash_size', '4MB')
        
        # 对于 ESP32-C2，如果频率是 40m，自动改为 60m
        if 'esp32c2' in chip_type.lower() or 'esp32-c2' in chip_type.lower():
            if current_freq == '40m':
                self.config['flash_freq'] = defaults['flash_freq']
                print(f"⚠️  注意: ESP32-C2 不支持 40m，已自动调整为 {defaults['flash_freq']}")
        
        # 如果配置的 flash_size 可能过大，给出警告（但不自动修改，因为可能用户知道自己在做什么）
        # 这里只是确保有合理的默认值
        if not self.config.get('flash_freq'):
            self.config['flash_freq'] = defaults['flash_freq']
        if not self.config.get('flash_size'):
            self.config['flash_size'] = defaults['flash_size']
        if not self.config.get('flash_mode'):
            self.config['flash_mode'] = defaults['flash_mode']
    
    def flash_firmware(self, port=None, firmware_path=None):
        """烧录固件"""
        # 检查esptool是否可用
        esptool_path = self.check_esptool()
        
        # 使用参数或配置文件中的值
        port = port or self.config['serial_port']
        firmware_path = firmware_path or self.config['firmware_path']
        
        # 检查固件文件
        if not os.path.exists(firmware_path):
            print(f"错误: 固件文件不存在: {firmware_path}")
            return False
        
        # 检查串口是否存在
        if not os.path.exists(port):
            print(f"错误: 串口设备不存在: {port}")
            print("\n提示: 使用 --list 参数查看可用的串口设备")
            return False
        
        # 显示模式信息
        mode = self.config.get('mode', 'unknown')
        mode_desc = self.config.get('description', '')
        encrypt = self.config.get('encrypt', False)
        
        print(f"\n开始烧录固件...")
        print(f"模式: {mode.upper()}" + (f" ({mode_desc})" if mode_desc else ""))
        if encrypt:
            print(f"⚠️  加密模式: 已启用")
        print(f"串口: {port}")
        print(f"波特率: {self.config['baud_rate']}")
        print(f"芯片类型: {self.config['chip_type']}")
        print(f"固件文件: {firmware_path}")
        print("-" * 60)
        
        # 根据芯片类型自动调整Flash参数
        self.adjust_flash_params()
        
        # 检测是否为combined固件
        is_combined = self.is_combined_firmware(firmware_path)
        if is_combined:
            print("检测到combined固件，将从0x0地址开始烧录")
        
        # 擦除Flash（如果需要）
        if self.config.get('erase_flash', False):
            print("正在擦除Flash...")
            print("-" * 60)
            erase_cmd = [
                esptool_path,
                '--port', port,
                '--baud', str(self.config['baud_rate']),
                '--chip', self.config['chip_type'],
                'erase-flash'
            ]
            try:
                process = subprocess.Popen(
                    erase_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                # 实时显示擦除进度
                while True:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    if output:
                        line = output.strip()
                        if line:
                            print(line)
                
                return_code = process.poll()
                if return_code != 0:
                    print(f"\n✗ 错误: 擦除Flash失败")
                    return False
                print("\n✓ Flash擦除完成")
            except subprocess.TimeoutExpired:
                print("\n✗ 错误: 擦除Flash超时")
                if 'process' in locals():
                    process.kill()
                return False
            except Exception as e:
                print(f"\n✗ 错误: 擦除Flash失败: {e}")
                return False
        
        # 构建烧录命令
        cmd_args = [
            esptool_path,
            '--port', port,
            '--baud', str(self.config['baud_rate']),
            '--chip', self.config['chip_type'],
        ]
        
        # 如果配置中要求不reset，添加 --after no-reset 参数（esptool v5.x 使用 --after 选项）
        # --after 是全局选项，必须放在 write-flash 子命令之前
        if not self.config.get('reset_after_flash', True):
            cmd_args.append('--after')
            cmd_args.append('no-reset')
        
        # 添加 write-flash 子命令及其选项
        cmd_args.extend([
            'write-flash',
            '--flash-mode', self.config.get('flash_mode', 'dio'),
            '--flash-freq', self.config.get('flash_freq', '40m'),
            '--flash-size', self.config.get('flash_size', '4MB'),
        ])
        
        # 注意：esptool v5.x 默认会验证，不需要 --verify 选项
        # 如果配置中明确要求不验证，可以使用 --no-verify（但通常不需要）
        if not self.config.get('verify', True):
            cmd_args.append('--no-verify')
        
        # 添加固件地址和路径
        # combined固件从0x0开始，普通固件从app_offset开始
        if is_combined:
            app_offset = '0x0'
        else:
            app_offset = self.config.get('app_offset', '0x10000')
        
        cmd_args.extend([app_offset, firmware_path])
        
        # 执行烧录（实时显示进度）
        try:
            print("正在烧录固件...")
            print(f"执行命令: {' '.join(cmd_args)}")
            print("-" * 60)
            
            # 创建日志文件（带时间戳）
            log_filename = f"esptool_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            log_file = open(log_filename, 'w', encoding='utf-8')
            log_file.write(f"ESP烧录日志 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"执行命令: {' '.join(cmd_args)}\n")
            log_file.write("=" * 80 + "\n\n")
            print(f"📝 日志文件: {log_filename}\n")
            
            # 使用Popen实时读取输出
            process = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # 实时读取并显示输出（改进的进度显示，从日志中解析）
            max_progress = -1  # 记录最大进度值，确保只显示递增的进度
            last_line = ""
            progress_line_active = False  # 标记是否正在显示进度行
            start_time = time.time()  # 记录开始时间
            total_bytes_original = None  # 记录原始总字节数（从Compressed行获取）
            total_bytes_compressed = None  # 记录压缩后总字节数（从Compressed行获取）
            bytes_written_known = None  # 记录已写入字节数
            bytes_written_is_compressed = False  # 标记已写入字节数是否是压缩后的
            last_progress_update_time = 0  # 记录上次进度更新的时间
            progress_update_lock = threading.Lock()  # 用于线程同步
            hash_verification_started = False  # Hash校验已开始（需要在后台线程之前定义）
            hash_verification_start_time = None  # Hash校验开始时间（用于超时检测）
            hash_verification_completed = False  # Hash校验是否已完成（完成后不再显示进度条）
            hash_verification_timeout = self.config.get('hash_verification_timeout', 15)  # 从配置读取超时时间，默认15秒
            flash_interrupted = False  # 标记是否被用户中断
            progress_100_shown = False  # 标记是否已经显示过100%进度条
            
            def format_time(seconds):
                """格式化时间显示为 MM:SS 或 HH:MM:SS"""
                seconds = int(max(0, seconds))
                h = seconds // 3600
                m = (seconds % 3600) // 60
                s = seconds % 60
                
                if h > 0:
                    # 超过一小时显示 HH:MM:SS
                    return f"{h:02d}:{m:02d}:{s:02d}"
                else:
                    # 否则显示 MM:SS
                    total_minutes = seconds // 60
                    remain_seconds = seconds % 60
                    return f"{total_minutes:02d}:{remain_seconds:02d}"
            
            def print_progress_bar(percent, bytes_written=None, total_bytes=None, force_update=False, newline=False):
                """在同一行显示进度条，包含时间和预计剩余时间
                newline: 如果为True，在进度达到100%时使用换行而不是\r
                """
                bar_width = 30
                filled = int(bar_width * percent / 100)
                bar = "█" * filled + "░" * (bar_width - filled)
                
                # 计算时间信息
                elapsed_time = time.time() - start_time
                elapsed_str = format_time(elapsed_time)
                
                # 计算预计剩余时间（只在进度>0时计算）
                if percent > 0:
                    estimated_total = elapsed_time / (percent / 100)
                    remaining_time = estimated_total - elapsed_time
                    remaining_str = format_time(max(0, remaining_time))
                else:
                    remaining_str = "计算中..."
                
                # 构建进度文本（时间用 已用/总计 的形式）
                base_text = f"  [{bar}] {percent:3d}%"
                
                # 添加字节信息（如果有）
                if bytes_written and total_bytes:
                    base_text += f" ({bytes_written}/{total_bytes} bytes)"
                elif bytes_written:
                    base_text += f" ({bytes_written} bytes)"
                
                # 添加时间信息（例如 00:04/01:22）
                if percent > 0:
                    # 预估总时间 = 已用 + 剩余
                    total_time = elapsed_time + max(0, remaining_time)
                    total_str = format_time(total_time)
                    time_text = f"{elapsed_str}/{total_str}"
                else:
                    time_text = f"{elapsed_str}/--:--"
                
                progress_text = f"{base_text} | 时间: {time_text}"
                
                # 如果newline为True且进度达到100%，使用换行；否则使用\r在同一行更新
                if newline and percent == 100:
                    print(f"{progress_text}", flush=True)
                else:
                    print(f"\r{progress_text}", end='', flush=True)
            
            def parse_progress_from_line(line):
                """从日志行中解析进度信息，支持多种格式
                返回: (percent, bytes_written, total_bytes, is_compressed_bytes)
                is_compressed_bytes: True表示bytes_written是压缩后的，False表示是原始的
                """
                # 格式1: "45% (12345 bytes)"
                # 格式2: "45% (12345/56789 bytes)"
                # 格式3: "Writing at 0x00001000... (45%)"
                # 格式4: "Wrote 12345 bytes (45%)"
                # 格式5: "Compressed 2097152 bytes to 76596..." (原始大小是2097152，压缩后是76596)
                # 格式6: "Wrote 32768 bytes (32768/76596 bytes)" (压缩后的字节数)
                # 格式7: "[████...] 100% (2097152/2097152 bytes)" (esptool v5的进度条格式)
                
                percent = None
                bytes_written = None
                total_bytes = None
                is_compressed_bytes = False  # 默认假设是原始字节数
                
                # 首先检查是否是 "Compressed" 行，提取原始大小和压缩后大小
                compressed_match = re.search(r'Compressed\s+(\d+)\s+bytes\s+to\s+(\d+)', line, re.IGNORECASE)
                if compressed_match:
                    # 原始大小和压缩后大小
                    original_size = compressed_match.group(1)
                    compressed_size = compressed_match.group(2)
                    # Compressed 行本身不包含进度百分比，只提供总数
                    # 返回特殊标记，让调用者知道这是压缩信息
                    return ('compressed_info', original_size, compressed_size, None)
                
                # 尝试匹配进度条格式："[████...] 100% (2097152/2097152 bytes)" 或 "[====] 100.0% 76596/76596 bytes"
                # 格式1：带括号的
                progress_bar_match = re.search(r'\[.*?\]\s*(\d+(?:\.\d+)?)%\s*\((\d+)/(\d+)\s*bytes\)', line)
                if progress_bar_match:
                    percent = int(float(progress_bar_match.group(1)))  # 支持小数百分比
                    bytes_written = progress_bar_match.group(2)
                    total_bytes = progress_bar_match.group(3)
                    # 判断是压缩后的还是原始的：如果总数接近压缩后大小，则是压缩后的
                    if total_bytes_compressed and abs(int(total_bytes) - int(total_bytes_compressed)) < 1000:
                        is_compressed_bytes = True
                    elif total_bytes_original and abs(int(total_bytes) - int(total_bytes_original)) < 1000:
                        is_compressed_bytes = False
                    return (percent, bytes_written, total_bytes, is_compressed_bytes)
                
                # 格式2：不带括号的 "[====] 100.0% 76596/76596 bytes"
                progress_bar_match2 = re.search(r'\[.*?\]\s*(\d+(?:\.\d+)?)%\s+(\d+)/(\d+)\s*bytes', line)
                if progress_bar_match2:
                    percent = int(float(progress_bar_match2.group(1)))  # 支持小数百分比
                    bytes_written = progress_bar_match2.group(2)
                    total_bytes = progress_bar_match2.group(3)
                    # 判断是压缩后的还是原始的：如果总数接近压缩后大小，则是压缩后的
                    if total_bytes_compressed and abs(int(total_bytes) - int(total_bytes_compressed)) < 1000:
                        is_compressed_bytes = True
                    elif total_bytes_original and abs(int(total_bytes) - int(total_bytes_original)) < 1000:
                        is_compressed_bytes = False
                    return (percent, bytes_written, total_bytes, is_compressed_bytes)
                
                # 尝试匹配百分比
                percent_match = re.search(r'(\d+)%', line)
                if percent_match:
                    percent = int(percent_match.group(1))
                
                # 尝试匹配字节信息：格式 "12345/56789 bytes" 或 "12345 bytes"
                bytes_match = re.search(r'(\d+)\s*/\s*(\d+)\s*bytes', line)
                if bytes_match:
                    bytes_written = bytes_match.group(1)
                    total_bytes = bytes_match.group(2)
                    # 判断是压缩后的还是原始的
                    if total_bytes_compressed and abs(int(total_bytes) - int(total_bytes_compressed)) < 1000:
                        is_compressed_bytes = True
                    elif total_bytes_original and abs(int(total_bytes) - int(total_bytes_original)) < 1000:
                        is_compressed_bytes = False
                    # 如果总数明显小于原始大小（比如小于10%），很可能是压缩后的
                    elif total_bytes_original and int(total_bytes) < total_bytes_original * 0.1:
                        is_compressed_bytes = True
                else:
                    # 尝试匹配单个字节数（在百分比附近）
                    bytes_single = re.search(r'(\d+)\s*bytes', line)
                    if bytes_single:
                        bytes_written = bytes_single.group(1)
                
                # 尝试从 "Wrote" 或 "Writing" 中提取信息
                wrote_match = re.search(r'(?:wrote|writing)\s+(\d+)\s*(?:/\s*(\d+))?\s*bytes', line, re.IGNORECASE)
                if wrote_match:
                    bytes_written = wrote_match.group(1)
                    if wrote_match.group(2):
                        total_bytes = wrote_match.group(2)
                        # 判断是压缩后的还是原始的
                        if total_bytes_compressed and abs(int(total_bytes) - int(total_bytes_compressed)) < 1000:
                            is_compressed_bytes = True
                        elif total_bytes_original and abs(int(total_bytes) - int(total_bytes_original)) < 1000:
                            is_compressed_bytes = False
                
                return (percent, bytes_written, total_bytes, is_compressed_bytes)
            
            # 后台线程：定期更新时间信息（即使进度百分比不变）
            def update_time_periodically():
                """定期更新进度条的时间信息，让用户知道程序还在运行"""
                nonlocal flash_interrupted, max_progress, progress_line_active, hash_verification_started, hash_verification_start_time, hash_verification_completed, hash_verification_timeout, bytes_written_known, bytes_written_is_compressed, total_bytes_compressed, total_bytes_original
                while not flash_interrupted:
                    try:
                        time.sleep(1)  # 每秒更新一次
                    except KeyboardInterrupt:
                        flash_interrupted = True
                        break
                    with progress_update_lock:
                        if flash_interrupted:
                            break
                        # 如果进度达到100%，不再更新时间，而是显示等待hash校验
                        if max_progress >= 100:
                            # 如果hash校验已完成，不再显示任何内容
                            if hash_verification_completed:
                                # Hash校验已完成，停止更新
                                pass
                            elif hash_verification_started:
                                # 检查超时（从配置读取超时时间）
                                # 确保hash_verification_start_time已设置
                                if hash_verification_start_time is None:
                                    hash_verification_start_time = time.time()
                                elapsed = time.time() - hash_verification_start_time
                                if elapsed > hash_verification_timeout:
                                    # 超时了，显示错误
                                    if progress_line_active:
                                        print("\r" + " " * 100 + "\r", end="", flush=True)
                                        print(f"  ✗ Hash校验超时（>{hash_verification_timeout}秒）", end="", flush=True)
                                else:
                                    # 还在等待中，显示等待提示（格式：已等待时间/超时时间）
                                    if progress_line_active:
                                        print("\r" + " " * 100 + "\r", end="", flush=True)
                                        print(f"  🔍 等待Hash校验... ({int(elapsed)}/{hash_verification_timeout}s)", end="", flush=True)
                            # 注意：当hash校验开始时，不再显示进度条，只显示hash校验倒计时
                        elif progress_line_active and max_progress >= 0:
                            # 进度未到100%，更新时间信息（百分比保持不变，只更新时间）
                            final_bytes = bytes_written_known if bytes_written_known else None
                            # 根据 bytes_written_is_compressed 选择正确的总数
                            if bytes_written_is_compressed:
                                final_total = total_bytes_compressed
                            else:
                                final_total = total_bytes_original
                            print_progress_bar(max_progress, final_bytes, final_total, force_update=True)
            
            # 启动后台线程
            time_update_thread = threading.Thread(target=update_time_periodically, daemon=True)
            time_update_thread.start()
            
            # 状态跟踪：压缩数据传输完成，等待Flash写入
            compressed_upload_complete = False
            flash_write_started = False
            
            # 使用迭代器逐行读取，确保捕获所有输出
            try:
                for line in iter(process.stdout.readline, ''):
                    if flash_interrupted:
                        break
                    if not line and process.poll() is not None:
                        break
                    
                    # 立即写入日志文件（包含原始换行符）
                    log_file.write(line)
                    log_file.flush()  # 确保立即写入
                    
                    line = line.rstrip()
                    
                    # 跳过完全空的行
                    if not line.strip():
                        continue
                    
                    # 从日志中解析进度信息
                    result = parse_progress_from_line(line)
                    
                    # 处理 Compressed 行的特殊返回值
                    if isinstance(result[0], str) and result[0] == 'compressed_info':
                        total_bytes_original = int(result[1])  # 原始大小
                        total_bytes_compressed = int(result[2])  # 压缩后大小
                        continue  # 继续处理下一行
                    
                    percent, bytes_written, total_bytes, is_compressed_bytes = result
                
                    # 更新已写入字节数
                    if bytes_written:
                        bytes_value = int(bytes_written)
                        # 只有当新值更大时才更新
                        if not bytes_written_known or bytes_value > bytes_written_known:
                            bytes_written_known = bytes_value
                            bytes_written_is_compressed = is_compressed_bytes
                
                    # 如果从字节数可以计算百分比，且没有百分比信息
                    if percent is None and bytes_written_known:
                        # 根据字节数类型选择正确的总数
                        if bytes_written_is_compressed and total_bytes_compressed:
                            # 使用压缩后的总数
                            percent = int((bytes_written_known / total_bytes_compressed) * 100)
                        elif not bytes_written_is_compressed and total_bytes_original:
                            # 使用原始总数
                            percent = int((bytes_written_known / total_bytes_original) * 100)
                
                    # 如果从当前行解析到了字节数，且字节数等于总数，强制设置为100%
                    if bytes_written and total_bytes:
                        if int(bytes_written) == int(total_bytes):
                            # 如果这是压缩数据且总数匹配压缩后大小，应该是100%
                            if is_compressed_bytes and total_bytes_compressed and abs(int(total_bytes) - int(total_bytes_compressed)) < 1000:
                                percent = 100
                            # 如果这是原始数据且总数匹配原始大小，应该是100%
                            elif not is_compressed_bytes and total_bytes_original and abs(int(total_bytes) - int(total_bytes_original)) < 1000:
                                percent = 100
                
                    # 如果已知字节数达到压缩总数，强制设置为100%
                    if bytes_written_known and bytes_written_is_compressed and total_bytes_compressed:
                        if int(bytes_written_known) >= int(total_bytes_compressed):
                            percent = 100
                
                    # 检测压缩数据传输完成
                    if percent == 100 and bytes_written_is_compressed and total_bytes_compressed:
                        if int(bytes_written_known) >= total_bytes_compressed:
                            compressed_upload_complete = True
                            # 进度达到100%后，开始等待hash校验
                            if not hash_verification_started:
                                hash_verification_started = True
                                hash_verification_start_time = time.time()  # 记录开始时间
                
                    # 检测Flash写入完成（出现"Wrote"消息）
                    if 'wrote' in line.lower() and not flash_write_started:
                        flash_write_started = True
                        compressed_upload_complete = False  # 重置状态
                        # 如果还没开始hash校验，现在开始
                        if not hash_verification_started:
                            hash_verification_started = True
                            hash_verification_start_time = time.time()  # 记录开始时间
                
                    # 检测Hash校验完成
                    if 'hash' in line.lower() and 'verified' in line.lower():
                        with progress_update_lock:
                            # 更新等待提示为完成信息，保留在log中
                            if progress_line_active and hash_verification_started:
                                # print("\r" + " " * 100 + "\r", end="", flush=True)  # 清除当前行
                                print("\n")
                                print(f"  ✓ Hash校验完成", flush=True)  # 显示完成信息并换行，保留在log中
                                progress_line_active = False
                        hash_verification_started = False  # Hash校验完成
                        hash_verification_start_time = None  # 清除开始时间
                        hash_verification_completed = True  # 标记已完成
                
                    # 如果有进度信息，更新显示
                    # 规则：
                    # 1. hash校验完成后，不再显示任何进度条
                    # 2. 进度未到100%时，如果hash校验已开始，不再显示进度条
                    # 3. 进度达到100%时，即使hash校验已开始，也要显示一次（如果还没显示过）
                    if percent is not None and not hash_verification_completed:
                        # 如果进度未到100%且hash校验已开始，跳过显示
                        if percent < 100 and hash_verification_started:
                            # 更新max_progress但不显示
                            if percent > max_progress:
                                max_progress = percent
                        else:
                            # 进度达到100%或hash校验未开始，可以显示
                            with progress_update_lock:
                                # 只显示递增的进度（避免显示倒退的进度）
                                if percent > max_progress:
                                    max_progress = percent
                                # 如果进度达到100%，立即开始等待hash校验
                                if percent == 100:
                                    # 如果还没显示过100%进度条，现在显示
                                    if not progress_100_shown:
                                        progress_100_shown = True  # 标记已显示
                                        # 确保hash校验已开始，并设置开始时间
                                        if not hash_verification_started:
                                            hash_verification_started = True
                                            hash_verification_start_time = time.time()
                                        # 如果hash_verification_started为True但hash_verification_start_time为None，也设置它
                                        elif hash_verification_start_time is None:
                                            hash_verification_start_time = time.time()
                                        # 显示100%进度条一次，然后切换到等待hash校验
                                        if bytes_written and total_bytes:
                                            final_bytes = int(bytes_written)
                                            if is_compressed_bytes:
                                                final_total = int(total_bytes) if total_bytes_compressed is None or abs(int(total_bytes) - int(total_bytes_compressed)) < 1000 else total_bytes_compressed
                                            else:
                                                final_total = int(total_bytes) if total_bytes_original is None or abs(int(total_bytes) - int(total_bytes_original)) < 1000 else total_bytes_original
                                        else:
                                            final_bytes = bytes_written_known if bytes_written_known else None
                                        if bytes_written_is_compressed:
                                            final_total = total_bytes_compressed
                                        else:
                                            final_total = total_bytes_original
                                        # 如果当前有进度条显示，先清除当前行并换行，然后显示100%进度条
                                        if progress_line_active:
                                            print("\r" + " " * 100 + "\r", end="", flush=True)  # 清除当前行
                                        print_progress_bar(percent, final_bytes, final_total, newline=True)  # 直接换行，保留100%进度条在log中
                                        # 在新的一行显示等待hash校验提示（计算实际已等待时间）
                                        # 确保hash_verification_start_time已设置（防止显示0/20s后不更新）
                                        if hash_verification_start_time is None:
                                            hash_verification_start_time = time.time()
                                        elapsed = int(time.time() - hash_verification_start_time)
                                        # 清除当前行（如果有内容），然后在新行显示hash校验倒计时
                                        print("\r" + " " * 100 + "\r", end="", flush=True)  # 清除当前行
                                        print(f"  🔍 等待Hash校验... ({elapsed}/{hash_verification_timeout}s)", end="", flush=True)
                                        progress_line_active = True
                                        last_progress_update_time = time.time()
                                else:
                                    # 进度未到100%，正常显示进度条
                                    # 确定要显示的字节数和总数（确保匹配）
                                    if bytes_written and total_bytes:
                                        # 如果从当前行解析到了字节数，优先使用
                                        final_bytes = int(bytes_written)
                                        # 根据 is_compressed_bytes 选择正确的总数
                                        if is_compressed_bytes:
                                            final_total = int(total_bytes) if total_bytes_compressed is None or abs(int(total_bytes) - total_bytes_compressed) < 1000 else total_bytes_compressed
                                        else:
                                            final_total = int(total_bytes) if total_bytes_original is None or abs(int(total_bytes) - int(total_bytes_original)) < 1000 else total_bytes_original
                                    else:
                                        # 使用已知的字节信息
                                        final_bytes = bytes_written_known if bytes_written_known else None
                                        # 根据 bytes_written_is_compressed 选择正确的总数
                                        if bytes_written_is_compressed:
                                            final_total = total_bytes_compressed
                                        else:
                                            final_total = total_bytes_original
                                    print_progress_bar(percent, final_bytes, final_total)
                                    progress_line_active = True
                                    last_progress_update_time = time.time()
                    # 如果压缩数据传输完成但还没开始Flash写入，显示提示
                    elif compressed_upload_complete and not flash_write_started:
                        with progress_update_lock:
                            if progress_line_active:
                                # 清除进度行，显示新状态
                                print("\r" + " " * 100 + "\r", end="", flush=True)  # 清除当前行
                                print(f"  ⏳ 压缩数据传输完成，正在解压并写入Flash... ({total_bytes_original} 字节)", end="", flush=True)
                                progress_line_active = True
                                last_progress_update_time = time.time()
                    else:
                        # 检查是否是完成/成功消息
                        line_lower = line.lower()
                        is_complete = any(keyword in line_lower for keyword in [
                            'wrote', 'verified', 'success', 'done', 'complete', 
                            'leaving', 'hard resetting'
                        ])
                        
                        # 如果有活跃的进度行，先换行
                        if progress_line_active:
                            with progress_update_lock:
                                # 如果是完成消息且进度还没到100%，先显示100%
                                if is_complete and max_progress < 100:
                                    # 根据 bytes_written_is_compressed 选择正确的总数
                                    if bytes_written_is_compressed:
                                        final_total = total_bytes_compressed
                                    else:
                                        final_total = total_bytes_original
                                    print_progress_bar(100, bytes_written_known, final_total, newline=True)  # 直接换行，结束进度行
                                    max_progress = 100
                                progress_line_active = False
                        
                        # 显示所有其他信息（避免重复显示相同行）
                        if line != last_line:
                            # 根据内容类型格式化显示
                            if 'warning' in line_lower or 'deprecated' in line_lower:
                                print(f"  ⚠️  {line}", flush=True)
                            elif 'error' in line_lower or 'fail' in line_lower:
                                print(f"  ✗ {line}", flush=True)
                            elif any(keyword in line_lower for keyword in ['connecting', 'chip type', 'uploading', 'running', 'wrote', 'verified', 'success', 'done', 'complete']):
                                print(f"  {line}", flush=True)
                            else:
                                # 显示所有其他行（包括可能包含进度信息的行）
                                # 如果这行包含进度条格式，跳过显示（避免重复）
                                if not re.search(r'\[.*?\]\s*\d+(?:\.\d+)?%\s*\(?\d+/\d+\s*bytes\)?', line):
                                    print(f"  [RAW] {line}", flush=True)
                            last_line = line
            except KeyboardInterrupt:
                # 用户按 Ctrl+C，立即中断
                flash_interrupted = True
                print("\n\n⚠️  检测到用户中断（Ctrl+C），正在终止烧录进程...")
                if process and process.poll() is None:
                    try:
                        process.terminate()  # 先尝试优雅终止
                        try:
                            process.wait(timeout=2)  # 等待最多2秒
                        except subprocess.TimeoutExpired:
                            process.kill()  # 如果2秒内没结束，强制终止
                    except Exception as e:
                        # 如果终止失败，尝试强制 kill
                        try:
                            process.kill()
                        except:
                            pass
                # 关闭日志文件
                if 'log_file' in locals() and log_file:
                    try:
                        log_file.write("\n" + "=" * 80 + "\n")
                        log_file.write("用户中断烧录（Ctrl+C）\n")
                        log_file.close()
                    except:
                        pass
                raise  # 重新抛出异常，让外层的 except KeyboardInterrupt 处理
            
            # 如果被中断，不再继续执行后续代码
            if flash_interrupted:
                return False
            
            # 确保进度行结束（如果还在显示）
            with progress_update_lock:
                if progress_line_active:
                    # 如果还没到100%，显示100%
                    if max_progress < 100:
                        # 根据 bytes_written_is_compressed 选择正确的总数
                        if bytes_written_is_compressed:
                            final_total = total_bytes_compressed
                        else:
                            final_total = total_bytes_original
                        print_progress_bar(100, bytes_written_known, final_total, newline=True)  # 直接换行
                    progress_line_active = False
            
            # 关闭日志文件
            log_file.write("\n" + "=" * 80 + "\n")
            log_file.write(f"烧录结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.close()
            
            # 获取返回码
            return_code = process.poll()
            
            if return_code == 0:
                print("\n\n✓ 固件烧录成功!")
                print(f"📝 完整日志已保存到: {log_filename}")
                
                # 如果需要，重置设备
                if self.config.get('reset_after_flash', True):
                    print("正在重置设备...")
                    reset_cmd = [
                        esptool_path,
                        '--port', port,
                        '--chip', self.config['chip_type'],
                        'run'
                    ]
                    try:
                        subprocess.run(reset_cmd, capture_output=True, timeout=5)
                        print("✓ 设备已重置")
                    except:
                        pass  # 重置失败不影响
                
                return True
            else:
                print("\n\n✗ 固件烧录失败!")
                print(f"📝 完整日志已保存到: {log_filename}")
                return False
                
        except subprocess.TimeoutExpired:
            print("\n\n✗ 固件烧录超时（超过5分钟）")
            if 'process' in locals():
                process.kill()
            if 'log_file' in locals():
                log_file.write("\n" + "=" * 80 + "\n")
                log_file.write("错误: 烧录超时\n")
                log_file.close()
                print(f"📝 日志已保存到: {log_filename}")
            return False
        except FileNotFoundError:
            print(f"\n✗ 错误: 找不到esptool，请确保已安装: pip install esptool")
            if 'log_file' in locals():
                log_file.write("\n" + "=" * 80 + "\n")
                log_file.write("错误: 找不到esptool\n")
                log_file.close()
            return False
        except KeyboardInterrupt:
            print("\n\n⚠️  用户中断烧录")
            # 确保终止 subprocess（如果存在）
            if 'process' in locals() and process:
                try:
                    if process.poll() is None:  # 进程还在运行
                        process.terminate()  # 先尝试优雅终止
                        try:
                            process.wait(timeout=2)  # 等待最多2秒
                        except subprocess.TimeoutExpired:
                            process.kill()  # 如果2秒内没结束，强制终止
                except Exception as e:
                    # 如果终止失败，尝试强制 kill
                    try:
                        process.kill()
                    except:
                        pass
            # 关闭日志文件
            if 'log_file' in locals() and log_file:
                try:
                    log_file.write("\n" + "=" * 80 + "\n")
                    log_file.write("用户中断烧录\n")
                    log_file.close()
                    print(f"📝 日志已保存到: {log_filename}")
                except:
                    pass
            return False
        except Exception as e:
            print(f"\n✗ 固件烧录失败: {e}")
            import traceback
            traceback.print_exc()
            if 'log_file' in locals():
                log_file.write("\n" + "=" * 80 + "\n")
                log_file.write(f"异常: {e}\n")
                log_file.write(traceback.format_exc())
                log_file.close()
                print(f"📝 日志已保存到: {log_filename}")
            return False
    
    def flash_with_partitions(self):
        """烧录包含分区表的完整固件"""
        esptool_path = self.check_esptool()
        port = self.config['serial_port']
        
        cmd_args = [
            esptool_path,
            '--port', port,
            '--baud', str(self.config['baud_rate']),
            '--chip', self.config['chip_type'],
        ]
        
        # 如果配置中要求不reset，添加 --after no-reset 参数（esptool v5.x 使用 --after 选项）
        # --after 是全局选项，必须放在 write-flash 子命令之前
        if not self.config.get('reset_after_flash', True):
            cmd_args.append('--after')
            cmd_args.append('no-reset')
        
        # 添加 write-flash 子命令及其选项
        cmd_args.extend([
            'write-flash',
            '--flash-mode', self.config.get('flash_mode', 'dio'),
            '--flash-freq', self.config.get('flash_freq', '40m'),
            '--flash-size', self.config.get('flash_size', '4MB'),
        ])
        
        # 注意：esptool v5.x 默认会验证，不需要 --verify 选项
        if not self.config.get('verify', True):
            cmd_args.append('--no-verify')
        
        # 添加bootloader（如果配置了）
        if self.config.get('bootloader'):
            cmd_args.extend(['0x1000', self.config['bootloader']])
        
        # 添加分区表（如果配置了）
        if self.config.get('partition_table'):
            cmd_args.extend(['0x8000', self.config['partition_table']])
        
        # 添加应用程序
        app_offset = self.config.get('app_offset', '0x10000')
        cmd_args.extend([app_offset, self.config['firmware_path']])
        
        try:
            print("正在烧录完整固件（包含bootloader和分区表）...")
            result = subprocess.run(cmd_args, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                print("\n✓ 固件烧录成功!")
                return True
            else:
                print("\n✗ 固件烧录失败!")
                if result.stderr:
                    print(result.stderr)
                return False
        except Exception as e:
            print(f"\n✗ 固件烧录失败: {e}")
            return False
    
    def execute_procedures(self):
        """执行配置文件中定义的procedures流程"""
        if 'procedures' not in self.config or not self.config['procedures']:
            print("⚠️  配置文件中没有定义procedures，跳过流程执行")
            return True
        
        print("\n" + "=" * 80)
        print("开始执行开发模式流程")
        print("=" * 80)
        
        # 存储执行过程中的状态信息
        self.procedure_state = {
            'encryption_status': None,
            'monitored_data': {
                'mac_address': None,
                'pressure_sensor': None,
                'rtc_time': None,
                'button_pressed': False
            },
            'detected_prompts': {}  # 记录已检测到的提示，用于自动流转
        }
        
        # 执行每个procedure
        for procedure in self.config['procedures']:
            print(f"\n执行流程: {procedure.get('name', 'unknown')}")
            print(f"描述: {procedure.get('description', '')}")
            print("-" * 80)
            
            if not self._execute_steps(procedure.get('steps', [])):
                print(f"\n✗ 流程执行失败: {procedure.get('name', 'unknown')}")
                return False
        
        print("\n" + "=" * 80)
        print("✓ 所有流程执行完成")
        print("=" * 80)
        return True
    
    def _execute_steps(self, steps):
        """递归执行步骤列表"""
        for step in steps:
            step_name = step.get('name', 'unknown')
            step_type = step.get('type', 'unknown')
            step_desc = step.get('description', '')
            
            print(f"\n[步骤] {step_name} ({step_type})")
            if step_desc:
                print(f"  描述: {step_desc}")
            
            try:
                result = self._execute_step(step)
                if not result:
                    on_failure = step.get('on_failure', 'error')
                    if on_failure == 'error':
                        print(f"✗ 步骤失败: {step_name}")
                        return False
                    elif on_failure == 'warning':
                        print(f"⚠️  步骤警告: {step_name}，继续执行")
                    # on_failure == 'ignore' 时继续执行
            except Exception as e:
                print(f"✗ 步骤执行异常: {step_name} - {e}")
                import traceback
                traceback.print_exc()
                on_failure = step.get('on_failure', 'error')
                if on_failure == 'error':
                    return False
            
            # 如果有子步骤，递归执行
            if 'steps' in step and step['steps']:
                if not self._execute_steps(step['steps']):
                    return False
        
        return True
    
    def _execute_step(self, step):
        """执行单个步骤"""
        step_type = step.get('type', 'unknown')
        
        if step_type == 'check_uart':
            return self._step_check_uart(step)
        elif step_type == 'check_encryption':
            return self._step_check_encryption(step)
        elif step_type == 'conditional':
            return self._step_conditional(step)
        elif step_type == 'flash_firmware':
            return self._step_flash_firmware(step)
        elif step_type == 'error':
            return self._step_error(step)
        elif step_type == 'reset_and_monitor':
            return self._step_reset_and_monitor(step)
        elif step_type == 'print_info':
            return self._step_print_info(step)
        elif step_type == 'wait_for_prompt':
            return self._step_wait_for_prompt(step)
        elif step_type == 'interactive_input':
            return self._step_interactive_input(step)
        elif step_type == 'self_test':
            # self_test 类型会通过 steps 递归处理
            return True
        else:
            print(f"⚠️  未知的步骤类型: {step_type}")
            return True
    
    def _step_check_uart(self, step):
        """检查UART串口是否存在"""
        port = self.config.get('serial_port')
        timeout = step.get('timeout', 5)
        
        print(f"  检查串口: {port}")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if os.path.exists(port):
                print(f"  ✓ 串口存在: {port}")
                return True
            time.sleep(0.5)
        
        print(f"  ✗ 串口不存在或超时: {port}")
        return False
    
    def _step_check_encryption(self, step):
        """通过监控ESP日志检查加密状态"""
        port = self.config.get('serial_port')
        monitor_baud = self.config.get('monitor_baud', 115200)
        timeout = step.get('timeout', 10)
        log_patterns = step.get('log_patterns', {})
        
        encrypted_patterns = log_patterns.get('encrypted', [])
        not_encrypted_patterns = log_patterns.get('not_encrypted', [])
        
        print(f"  监控串口: {port} (波特率: {monitor_baud})")
        print(f"  超时: {timeout}秒")
        
        monitor = SerialMonitor(port, monitor_baud)
        if not monitor.open():
            print("  ✗ 无法打开串口进行监控")
            return False
        
        try:
            # 先清空串口缓冲区，确保从干净状态开始
            if monitor.serial_conn:
                monitor.serial_conn.reset_input_buffer()
                monitor.serial_conn.reset_output_buffer()
            
            print("  ✓ 串口已打开，开始监控...")
            
            # 立即开始监控循环（在复位之前就开始读取，确保不丢失任何数据）
            start_time = time.time()
            buffer = ""
            encryption_detected = None
            
            # 先短暂监控一下，确保串口稳定
            time.sleep(0.2)
            
            # 复位设备以触发启动日志（通过串口DTR/RTS信号）
            if monitor.serial_conn:
                print("  → 正在复位设备...")
                monitor.serial_conn.dtr = False
                monitor.serial_conn.rts = False
                time.sleep(0.1)
                monitor.serial_conn.dtr = True
                monitor.serial_conn.rts = True
                time.sleep(0.2)  # 短暂等待复位完成
            
            print("  ✓ 设备已复位，继续监控日志...")
            
            # ANSI转义码正则表达式
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            
            # 持续监控日志
            while time.time() - start_time < timeout:
                if monitor.serial_conn and monitor.serial_conn.in_waiting > 0:
                    data = monitor.serial_conn.read(monitor.serial_conn.in_waiting)
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text
                    
                    # 按行处理，提高匹配准确性
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        # 去除ANSI转义码
                        line_clean = ansi_escape.sub('', line)
                        line_clean = line_clean.strip()
                        if line_clean:
                            # 检查加密模式
                            for pattern in encrypted_patterns:
                                if pattern.lower() in line_clean.lower():
                                    encryption_detected = True
                                    print(f"  ✓ 检测到加密状态: {pattern}")
                                    break
                            
                            if encryption_detected is None:
                                for pattern in not_encrypted_patterns:
                                    if pattern.lower() in line_clean.lower():
                                        encryption_detected = False
                                        print(f"  ✓ 检测到未加密状态: {pattern}")
                                        break
                            
                            if encryption_detected is not None:
                                break
                    
                    # 如果已经检测到，提前退出
                    if encryption_detected is not None:
                        break
                
                time.sleep(0.05)  # 减少延迟，提高响应速度
            
            monitor.close()
            
            if encryption_detected is None:
                print(f"  ⚠️  超时未检测到加密状态，假设未加密")
                encryption_detected = False
            
            self.procedure_state['encryption_status'] = 'encrypted' if encryption_detected else 'not_encrypted'
            return True
            
        except Exception as e:
            print(f"  ✗ 检查加密状态时出错: {e}")
            import traceback
            traceback.print_exc()
            monitor.close()
            return False
    
    def _step_conditional(self, step):
        """条件判断步骤"""
        condition = step.get('condition', '')
        condition_value = self.procedure_state.get('encryption_status')
        
        print(f"  条件: {condition}, 当前值: {condition_value}")
        
        # 检查条件是否满足
        condition_met = False
        if condition == 'not_encrypted':
            condition_met = (condition_value == 'not_encrypted')
        elif condition == 'encrypted':
            condition_met = (condition_value == 'encrypted')
        
        if condition_met:
            print(f"  ✓ 条件满足，执行 on_condition_true")
            steps = step.get('on_condition_true', [])
        else:
            print(f"  ✓ 条件不满足，执行 on_condition_false")
            steps = step.get('on_condition_false', [])
        
        return self._execute_steps(steps)
    
    def _step_flash_firmware(self, step):
        """执行固件烧录"""
        timeout = step.get('timeout', 300)
        print(f"  执行固件烧录 (超时: {timeout}秒)")
        return self.flash_firmware()
    
    def _step_error(self, step):
        """错误步骤 - 显示错误信息并退出"""
        message = step.get('message', '发生错误')
        exit_on_error = step.get('exit', False)
        
        print(f"  ✗ 错误: {message}")
        
        if exit_on_error:
            print("\n程序退出")
            sys.exit(1)
        
        return False
    
    def _step_reset_and_monitor(self, step):
        """复位设备并监控日志"""
        port = self.config.get('serial_port')
        monitor_baud = self.config.get('monitor_baud', 115200)
        timeout = step.get('timeout', 60)
        log_patterns = step.get('log_patterns', {})
        extract_mac = step.get('extract_mac', False)
        extract_pressure = step.get('extract_pressure', False)
        extract_rtc = step.get('extract_rtc', False)
        monitor_button = step.get('monitor_button', False)
        
        print(f"  复位设备并监控日志 (超时: {timeout}秒)")
        
        monitor = SerialMonitor(port, monitor_baud)
        if not monitor.open():
            print("  ✗ 无法打开串口进行监控")
            return False
        
        try:
            # 先清空串口缓冲区，确保从干净状态开始
            if monitor.serial_conn:
                monitor.serial_conn.reset_input_buffer()
                monitor.serial_conn.reset_output_buffer()
            
            print("  ✓ 串口已打开，开始监控...")
            
            # 立即开始监控循环（在复位之前就开始读取，确保不丢失任何数据）
            start_time = time.time()
            buffer = ""
            monitored_data = self.procedure_state['monitored_data']
            
            # 标志位，避免重复打印
            boot_complete_printed = False
            mac_extracted = False
            pressure_extracted = False
            rtc_extracted = False
            button_detected = False
            button_pressed = False  # 记录按钮是否已按下
            
            # 测试状态跟踪
            test_states = step.get('test_states', {})
            current_test_state = None
            detected_states = set()  # 记录已检测到的状态，避免重复显示
            
            # 自动流转配置
            auto_advance = step.get('auto_advance_on', {})
            wait_for_button = auto_advance.get('wait_for_button', False)
            button_prompt = auto_advance.get('button_prompt', 'Press button to continue')
            
            # 先短暂监控一下，确保串口稳定
            time.sleep(0.2)
            
            # 复位设备（通过串口DTR/RTS信号）
            if monitor.serial_conn:
                print("  → 正在复位设备...")
                monitor.serial_conn.dtr = False
                monitor.serial_conn.rts = False
                time.sleep(0.1)
                monitor.serial_conn.dtr = True
                monitor.serial_conn.rts = True
                time.sleep(0.2)  # 短暂等待复位完成
            
            print("  ✓ 设备已复位，继续监控日志...")
            print("  📊 当前测试状态: 等待设备启动...")
            
            # 持续监控日志
            while time.time() - start_time < timeout:
                if monitor.serial_conn and monitor.serial_conn.in_waiting > 0:
                    data = monitor.serial_conn.read(monitor.serial_conn.in_waiting)
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text
                    
                    # 按行处理
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        # 去除ANSI转义码
                        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                        line_clean = ansi_escape.sub('', line)
                        line_clean = line_clean.strip()
                        if line_clean:
                            print(f"  [日志] {line_clean}")
                            
                            # 检查并更新测试状态
                            for state_name, state_config in test_states.items():
                                if state_name not in detected_states:
                                    patterns = state_config.get('patterns', [])
                                    for pattern in patterns:
                                        if pattern.lower() in line_clean.lower():
                                            message = state_config.get('message', f'测试: {state_name}')
                                            if current_test_state != state_name:
                                                print(f"  {message}")
                                                current_test_state = state_name
                                                detected_states.add(state_name)
                                            break
                            
                            # 提取MAC地址（只提取一次）
                            # 注意：ESP32-C2的MAC地址通常不会在启动日志中自动输出
                            # 需要应用程序主动输出才能检测到
                            if extract_mac and not mac_extracted:
                                mac_patterns = log_patterns.get('mac_address', [])
                                for pattern in mac_patterns:
                                    if pattern.lower() in line_clean.lower():
                                        # 尝试提取MAC地址
                                        mac_match = re.search(r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})', line_clean, re.IGNORECASE)
                                        if mac_match:
                                            monitored_data['mac_address'] = mac_match.group(0)
                                            print(f"  ✓ 提取到MAC地址: {monitored_data['mac_address']}")
                                            mac_extracted = True
                                            break
                            
                            # 提取压力传感器信息（只提取第一次有效读数）
                            if extract_pressure and not pressure_extracted:
                                pressure_patterns = log_patterns.get('pressure_sensor', [])
                                for pattern in pressure_patterns:
                                    if pattern.lower() in line_clean.lower() and 'Reading:' in line_clean:
                                        monitored_data['pressure_sensor'] = line_clean
                                        print(f"  ✓ 检测到压力传感器: {line_clean}")
                                        pressure_extracted = True
                                        break
                            
                            # 提取RTC时间（只提取第一次）
                            if extract_rtc and not rtc_extracted:
                                rtc_patterns = log_patterns.get('rtc_time', [])
                                for pattern in rtc_patterns:
                                    if pattern.lower() in line_clean.lower() and 'RTC Time now:' in line_clean:
                                        monitored_data['rtc_time'] = line_clean
                                        print(f"  ✓ 检测到RTC时间: {line_clean}")
                                        rtc_extracted = True
                                        break
                            
                            # 监控按钮状态
                            if monitor_button:
                                button_patterns = log_patterns.get('button_pressed', [])
                                for pattern in button_patterns:
                                    if pattern.lower() in line_clean.lower():
                                        if not button_detected:
                                            monitored_data['button_pressed'] = True
                                            print(f"  ✓ 检测到按钮按下提示")
                                            button_detected = True
                                            if wait_for_button:
                                                print(f"  ⏸️  等待用户按下按钮...")
                                        break
                            
                            # 检测按钮是否真的被按下（通过检测后续测试步骤）
                            if wait_for_button and button_detected and not button_pressed:
                                # 按钮按下后，设备会继续执行LED、阀门测试等
                                if any(keyword in line_clean.lower() for keyword in ['toggling led', 'toggling valve', 'leds', 'valve']):
                                    button_pressed = True
                                    print(f"  ✓ 按钮已按下，设备继续执行测试")
                            
                            # 检查是否启动完成（只打印一次）
                            if not boot_complete_printed:
                                boot_patterns = log_patterns.get('boot_complete', [])
                                for pattern in boot_patterns:
                                    if pattern.lower() in line_clean.lower():
                                        print(f"  ✓ 设备启动完成")
                                        boot_complete_printed = True
                                        break
                            
                            # 检查自动流转条件
                            if auto_advance:
                                advance_pattern = auto_advance.get('pattern', '')
                                if advance_pattern and advance_pattern.lower() in line_clean.lower():
                                    # 如果需要等待按钮，检查按钮是否已按下
                                    if wait_for_button:
                                        if not button_pressed:
                                            # 按钮还没按下，不能自动流转，继续等待
                                            print(f"  ⏸️  检测到硬件版本提示，但按钮尚未按下，继续等待...")
                                            continue
                                        else:
                                            # 按钮已按下，可以自动流转
                                            advance_desc = auto_advance.get('description', '检测到自动流转条件')
                                            print(f"  ✓ {advance_desc} (按钮已按下)")
                                    else:
                                        # 不需要等待按钮，直接流转
                                        advance_desc = auto_advance.get('description', '检测到自动流转条件')
                                        print(f"  ✓ {advance_desc}")
                                    
                                    # 记录检测到的提示
                                    self.procedure_state['detected_prompts'][advance_pattern] = True
                                    monitor.close()
                                    print(f"  → 自动进入下一步...")
                                    return True
                
                time.sleep(0.05)  # 减少延迟，提高响应速度
            
            monitor.close()
            print(f"  ✓ 监控完成")
            return True
            
        except Exception as e:
            print(f"  ✗ 监控过程中出错: {e}")
            import traceback
            traceback.print_exc()
            monitor.close()
            return False
    
    def _step_print_info(self, step):
        """打印监控到的信息"""
        info_types = step.get('info_types', [])
        monitored_data = self.procedure_state['monitored_data']
        
        print("  监控到的信息:")
        for info_type in info_types:
            value = monitored_data.get(info_type)
            if value:
                print(f"    {info_type}: {value}")
            else:
                print(f"    {info_type}: (未检测到)")
        
        return True
    
    def _step_wait_for_prompt(self, step):
        """等待特定提示出现"""
        port = self.config.get('serial_port')
        monitor_baud = self.config.get('monitor_baud', 115200)
        timeout = step.get('timeout', 30)
        prompt_pattern = step.get('prompt_pattern', '')
        skip_if_detected = step.get('skip_if_detected', False)
        
        # 检查是否已经检测到提示（自动流转）
        if skip_if_detected and prompt_pattern:
            detected_prompts = self.procedure_state.get('detected_prompts', {})
            if prompt_pattern in detected_prompts:
                print(f"  ✓ 提示已在之前步骤中检测到: {prompt_pattern}")
                print(f"  → 自动跳过，直接进入下一步...")
                return True
        
        # 获取测试状态配置（从父步骤或当前步骤）
        test_states = step.get('test_states', {})
        current_test_state = None
        detected_states = set()
        
        print(f"  等待提示: {prompt_pattern} (超时: {timeout}秒)")
        
        monitor = SerialMonitor(port, monitor_baud)
        if not monitor.open():
            print("  ✗ 无法打开串口进行监控")
            return False
        
        try:
            start_time = time.time()
            buffer = ""
            
            # ANSI转义码正则表达式
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            
            while time.time() - start_time < timeout:
                if monitor.serial_conn and monitor.serial_conn.in_waiting > 0:
                    data = monitor.serial_conn.read(monitor.serial_conn.in_waiting)
                    text = data.decode('utf-8', errors='ignore')
                    buffer += text
                    
                    # 按行处理
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        # 去除ANSI转义码后再处理
                        line_clean = ansi_escape.sub('', line)
                        line_clean = line_clean.strip()
                        if line_clean:
                            print(f"  [日志] {line_clean}")
                            
                            # 检查并更新测试状态
                            for state_name, state_config in test_states.items():
                                if state_name not in detected_states:
                                    patterns = state_config.get('patterns', [])
                                    for pattern in patterns:
                                        if pattern.lower() in line_clean.lower():
                                            message = state_config.get('message', f'测试: {state_name}')
                                            if current_test_state != state_name:
                                                print(f"  {message}")
                                                current_test_state = state_name
                                                detected_states.add(state_name)
                                            break
                            
                            # 去除ANSI转义码后匹配
                            if prompt_pattern.lower() in line_clean.lower():
                                print(f"  ✓ 检测到提示: {prompt_pattern}")
                                # 记录检测到的提示
                                self.procedure_state['detected_prompts'][prompt_pattern] = True
                                monitor.close()
                                return True
                
                time.sleep(0.05)  # 提高响应速度
            
            monitor.close()
            print(f"  ⚠️  超时未检测到提示: {prompt_pattern}")
            return False
            
        except Exception as e:
            print(f"  ✗ 等待提示时出错: {e}")
            import traceback
            traceback.print_exc()
            monitor.close()
            return False
    
    def _step_interactive_input(self, step):
        """交互式输入步骤"""
        port = self.config.get('serial_port')
        monitor_baud = self.config.get('monitor_baud', 115200)
        prompt = step.get('prompt', '请输入:')
        fallback_to_config = step.get('fallback_to_config', False)
        config_key = step.get('config_key', '')
        config_files = step.get('config_files', [])
        send_to_device = step.get('send_to_device', False)
        
        # 先从配置文件获取默认值
        default_value = None
        if fallback_to_config and config_key:
            for config_file in config_files:
                if os.path.exists(config_file):
                    try:
                        with open(config_file, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                            if config_key in config_data:
                                default_value = str(config_data[config_key]).strip()
                                break
                    except Exception as e:
                        continue
        
        # 构建提示信息，显示默认值
        if default_value:
            prompt_with_default = f"{prompt} [默认: {default_value}]"
        else:
            prompt_with_default = prompt
        
        print(f"  交互式输入: {prompt}")
        
        # 获取用户输入
        try:
            user_input = input(f"  {prompt_with_default}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("  ✗ 用户取消输入")
            return False
        
        # 如果用户输入为空，使用默认值
        if not user_input:
            if default_value:
                user_input = default_value
                print(f"  ✓ 使用默认值: {default_value}")
            elif fallback_to_config:
                print("  ⚠️  未在配置文件中找到默认值，且用户输入为空")
                return False
            else:
                print("  ✗ 输入为空")
                return False
        
        # 确保输入值被正确清理（去除所有空白字符，包括换行符）
        user_input = user_input.strip()
        
        if not user_input:
            print("  ✗ 输入为空")
            return False
        
        print(f"  ✓ 输入值: {user_input}")
        
        # 如果需要发送到设备
        if send_to_device:
            monitor = SerialMonitor(port, monitor_baud)
            if not monitor.open():
                print("  ✗ 无法打开串口发送数据")
                return False
            
            try:
                time.sleep(0.5)  # 等待提示完全显示
                # 清理输入：只移除 \n，保留 \r（如果配置值中包含 \r）
                # send_command 会自动添加 \n，所以 "P2V2\r" 会变成 "P2V2\r\n"（这是正确的）
                clean_input = user_input.replace('\n', '')
                # \r 会被自动保留，因为只移除了 \n
                if monitor.send_command(clean_input):
                    # 显示发送的值（将 \r 和 \n 显示为可见字符，方便调试）
                    display_value = clean_input.replace('\r', '\\r').replace('\n', '\\n')
                    print(f"  ✓ 已发送到设备: {display_value}")
                    monitor.close()
                    return True
                else:
                    print("  ✗ 发送到设备失败")
                    monitor.close()
                    return False
            except Exception as e:
                print(f"  ✗ 发送数据时出错: {e}")
                import traceback
                traceback.print_exc()
                monitor.close()
                return False
        
        return True


def run_tui_loop():
    """TUI main loop, supports Control+R restart"""
    while True:
        try:
            run_tui_once()
            # If successfully completed, ask if continue
            continue_question = [
                inquirer.Confirm('continue',
                                message="Continue using the tool? (Press Ctrl+R or Cmd+R to restart anytime)",
                                default=True)
            ]
            answer = inquirer.prompt(continue_question)
            if not answer or not answer.get('continue', False):
                print("\nExiting tool")
                break
        except KeyboardInterrupt:
            print("\n\nUser interrupted operation")
            break
        except Exception as e:
            print(f"\nError occurred: {e}")
            import traceback
            traceback.print_exc()
            break


def clear_screen():
    """Clear screen"""
    os.system('clear' if os.name != 'nt' else 'cls')


def print_centered(text, width=80):
    """Print centered text"""
    lines = text.split('\n')
    for line in lines:
        print(line.center(width))


def print_header(title, width=80):
    """Print formatted header"""
    # 使用更美观的边框字符
    top_border = "╔" + "═" * (width - 2) + "╗"
    bottom_border = "╚" + "═" * (width - 2) + "╝"
    
    # 标题行
    title_line = "║" + title.center(width - 2) + "║"
    
    print("\n" + top_border)
    print(title_line)
    print(bottom_border + "\n")


def print_section_header(title, width=80):
    """Print section header (smaller)"""
    border = "─" * (width - 4)
    print(f"  ┌{border}┐")
    print(f"  │ {title:<{width-6}} │")
    print(f"  └{border}┘")


def print_config_table(config_items, width=80):
    """Print configuration table with aligned formatting"""
    if not config_items:
        return
    
    # Calculate maximum label length
    max_label_len = max(len(label) for label, _ in config_items)
    # Set uniform label width
    label_width = max(max_label_len + 2, 16)
    value_width = width - label_width - 8  # Reserve space for borders and spacing
    
    # Table borders
    border_top = "  ┌" + "─" * (label_width + 2) + "┬" + "─" * (value_width + 2) + "┐"
    border_mid = "  ├" + "─" * (label_width + 2) + "┼" + "─" * (value_width + 2) + "┤"
    border_bot = "  └" + "─" * (label_width + 2) + "┴" + "─" * (value_width + 2) + "┘"
    
    print(border_top)
    
    for idx, (label, value) in enumerate(config_items):
        value_str = str(value) if value else "Not set"
        # Truncate if value is too long
        if len(value_str) > value_width:
            value_str = value_str[:value_width - 3] + "..."
        
        # Format row
        row = f"  │ {label:<{label_width}} │ {value_str:<{value_width}} │"
        print(row)
        
        # Add separator before last row
        if idx < len(config_items) - 1:
            print(border_mid)
    
    print(border_bot)


def run_tui_once():
    """Run hierarchical menu TUI interface"""
    # Try to import inquirer
    global inquirer
    if inquirer is None:
        try:
            import inquirer
        except ImportError:
            print("\n" + "="*80)
            print_centered("Error: inquirer library not installed", 80)
            print("="*80)
            print("\nAttempting to auto-install inquirer...")
            try:
                import subprocess
                pip_cmd = [sys.executable, '-m', 'pip', 'install', 'inquirer']
                result = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    print("✓ inquirer installed successfully!")
                    try:
                        import inquirer
                        print("Starting TUI interface...\n")
                    except ImportError:
                        print("Please run the command again to start TUI interface")
                        return
                else:
                    print("✗ Auto-installation failed")
                    if result.stderr:
                        print(result.stderr)
                    print("\nPlease manually run: pip install inquirer")
                    return
            except Exception as e:
                print(f"✗ Error during installation: {e}")
                print("Please manually run: pip install inquirer")
                return
    
    # Check again
    try:
        if inquirer is None:
            import inquirer
    except ImportError:
        print("Error: Unable to load inquirer library, please run: pip install inquirer")
        return
    
    # Configuration state
    config_state = {
        'mode': None,
        'config_path': None,
        'mode_name': None,
        'port': None,
        'baud_rate': None,
        'firmware': None,
        'monitor_baud': None,
        'version_string': None,
        'device_code_rule': None,
        'options': []
    }
    
    # Main menu loop
    while True:
        try:
            clear_screen()
            print_header("ESP Auto Flashing Tool", 80)
            
            # Main menu options (formatted design)
            print_centered("Please select working mode", 80)
            print()
            
            main_menu_choices = [
                ('  🔧  Develop Mode', 'develop_mode'),
                ('  🏭  Factory Mode', 'factory_mode'),
                ('  ❌  Exit', 'exit')
            ]
            
            main_menu = [
                inquirer.List('action',
                             message="",
                             choices=main_menu_choices)
            ]
            
            answer = inquirer.prompt(main_menu)
            if not answer:
                break
            
            action = answer['action']
            
            # Handle main menu selection
            if action == 'develop_mode':
                config_state = menu_mode_main(config_state, 'develop')
            elif action == 'factory_mode':
                config_state = menu_mode_main(config_state, 'factory')
            elif action == 'exit':
                clear_screen()
                print_header("Thank you for using", 80)
                break
                
        except KeyboardInterrupt:
            clear_screen()
            print("\n\nUser interrupted operation")
            break
        except RestartTUI:
            # Restart, reset configuration
            config_state = {
                'mode': None,
                'config_path': None,
                'mode_name': None,
                'port': None,
                'baud_rate': None,
                'firmware': None,
                'monitor_baud': None,
                'version_string': None,
                'device_code_rule': None,
                'options': []
            }
            continue
        except Exception as e:
            print(f"\nError occurred: {e}")
            import traceback
            traceback.print_exc()


def menu_mode_main(config_state, mode_type):
    """Mode main menu (Develop/Factory)"""
    mode_name = 'Develop Mode' if mode_type == 'develop' else 'Factory Mode'
    config_path = 'config_develop.json' if mode_type == 'develop' else 'config_factory.json'
    
    # Update configuration state
    if not config_state.get('mode') or config_state.get('mode') != mode_type:
        config_state['mode'] = mode_type
        config_state['mode_name'] = mode_name
        config_state['config_path'] = config_path
        
        # Load default configuration (using load_default_config to support reading default baud rate from config.json)
        default_config = load_default_config(config_path)
        if default_config:
            config_state['port'] = config_state.get('port') or default_config.get('serial_port')
            config_state['baud_rate'] = config_state.get('baud_rate') or default_config.get('baud_rate')
            config_state['firmware'] = config_state.get('firmware') or default_config.get('firmware_path')
            config_state['monitor_baud'] = config_state.get('monitor_baud') or default_config.get('monitor_baud')
    
    while True:
        try:
            clear_screen()
            print_header(f"{mode_name.upper()} MODE", 80)
            
            # Display current configuration summary (formatted table)
            print_section_header("Current Configuration Summary", 80)
            print()
            
            config_items = [
                ("Serial Port", config_state.get('port', 'Not set')),
                ("Flash Baud Rate", config_state.get('baud_rate', 'Not set')),
                ("Firmware", os.path.basename(config_state['firmware']) if config_state.get('firmware') else 'Not set'),
                ("Monitor Baud Rate", config_state.get('monitor_baud', 'Not set')),
                ("Version String", config_state.get('version_string', 'Not set')),
                ("Device Code Rule", config_state.get('device_code_rule', 'Not set'))
            ]
            print_config_table(config_items, 80)
            print()
            
            # Mode menu options (formatted design)
            print_centered("Please select operation", 80)
            print()
            
            mode_menu_choices = [
                ('  ▶️  Start Flashing', 'start'),
                ('  ⚙️  Settings', 'settings'),
                ('  ←  Back to Main Menu', 'back')
            ]
            
            mode_menu = [
                inquirer.List('action',
                             message="",
                             choices=mode_menu_choices)
            ]
            
            answer = inquirer.prompt(mode_menu)
            if not answer or answer['action'] == 'back':
                return config_state
            
            action = answer['action']
            
            if action == 'start':
                if menu_start_flash(config_state):
                    # Flashing successful
                    continue_choice = [
                        inquirer.Confirm('continue',
                                        message="Flashing completed, continue?",
                                        default=True)
                    ]
                    cont_answer = inquirer.prompt(continue_choice)
                    if not cont_answer or not cont_answer.get('continue', False):
                        return config_state
                # Continue loop on flashing failure
            elif action == 'settings':
                config_state = menu_settings(config_state, mode_type)
                
        except KeyboardInterrupt:
            return config_state
        except Exception as e:
            print(f"\nError occurred: {e}")


def load_default_config(config_path):
    """Load default configuration from config file, read from config.json if baud rate field is missing"""
    if not os.path.exists(config_path):
        return {}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # If it's dev or factory config file and missing baud rate field, read default values from config.json
        if config_path in ['config_develop.json', 'config_factory.json']:
            base_config_path = 'config.json'
            if os.path.exists(base_config_path):
                try:
                    with open(base_config_path, 'r', encoding='utf-8') as f:
                        base_config = json.load(f)
                    
                    # Fields that need to read default values from config.json: baud rate related fields, hash verification timeout, serial port filter config
                    default_fields = ['baud_rate', 'monitor_baud', 'hash_verification_timeout', 
                                     'filter_serial_ports', 'serial_port_keywords', 'exclude_port_patterns']
                    for field in default_fields:
                        if field not in config and field in base_config:
                            config[field] = base_config[field]
                except Exception as e:
                    # If reading config.json fails, ignore error and continue using current config
                    pass
        
        return config
    except Exception as e:
        print(f"Warning: Failed to load config file: {e}")
        return {}


def save_config_to_file(config_state):
    """Save configuration state to config file"""
    config_path = config_state.get('config_path')
    if not config_path:
        return False
    
    try:
        # Load existing configuration
        existing_config = load_default_config(config_path)
        
        # Update configuration values
        if config_state.get('port'):
            existing_config['serial_port'] = config_state['port']
        if config_state.get('baud_rate'):
            existing_config['baud_rate'] = config_state['baud_rate']
        if config_state.get('firmware'):
            existing_config['firmware_path'] = config_state['firmware']
        if config_state.get('monitor_baud'):
            existing_config['monitor_baud'] = config_state['monitor_baud']
        if config_state.get('version_string'):
            existing_config['version_string'] = config_state['version_string']
        if config_state.get('device_code_rule'):
            existing_config['device_code_rule'] = config_state['device_code_rule']
        
        # Save to file
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(existing_config, f, indent=2, ensure_ascii=False)
        
        return True
    except Exception as e:
        print(f"Error: Failed to save configuration: {e}")
        return False


def reload_default_config(config_state):
    """Reload default configuration (supports reading default baud rate from config.json)"""
    config_path = config_state.get('config_path')
    if not config_path:
        return config_state
    
    default_config = load_default_config(config_path)
    
    # Reload all default values
    if 'serial_port' in default_config:
        config_state['port'] = default_config['serial_port']
    if 'baud_rate' in default_config:
        config_state['baud_rate'] = default_config['baud_rate']
    if 'firmware_path' in default_config:
        config_state['firmware'] = default_config['firmware_path']
    if 'monitor_baud' in default_config:
        config_state['monitor_baud'] = default_config['monitor_baud']
    if 'version_string' in default_config:
        config_state['version_string'] = default_config['version_string']
    if 'device_code_rule' in default_config:
        config_state['device_code_rule'] = default_config['device_code_rule']
    
    print("\n✓ Default configuration reloaded")
    return config_state


def menu_settings(config_state, mode_type):
    """Settings menu"""
    last_selected = None  # Remember last selected setting item
    
    def format_current_value(value, max_len=25):
        """Format current value display"""
        if not value:
            return "Not set"
        value_str = str(value)
        if len(value_str) > max_len:
            return value_str[:max_len-3] + "..."
        return value_str
    
    while True:
        try:
            clear_screen()
            print_header("Settings", 80)
            
            # Get current configuration values
            current_port = config_state.get('port', '')
            current_baud = config_state.get('baud_rate', '')
            current_firmware = config_state.get('firmware', '')
            current_monitor_baud = config_state.get('monitor_baud', '')
            current_version = config_state.get('version_string', '')
            current_rule = config_state.get('device_code_rule', '')
            
            # Format firmware display (show filename only)
            firmware_display = 'Not set'
            if current_firmware:
                firmware_display = os.path.basename(current_firmware)
                if len(firmware_display) > 25:
                    firmware_display = firmware_display[:22] + "..."
            
            # Define option names and corresponding values, use tab alignment (concise and uniform)
            max_label_len = 14  # Length of "Device Code Rule"
            
            def format_option(label, value):
                """Format option with tab alignment"""
                # Use fixed width alignment, concise and beautiful
                label_padded = label.ljust(max_label_len)
                return f"{label_padded}\t→\t{value}"
            
            # Display current configuration values preview
            print_section_header("Current Configuration", 80)
            print()
            preview_items = [
                ("Serial Port", format_current_value(current_port, 20)),
                ("Flash Baud Rate", format_current_value(current_baud)),
                ("Firmware", firmware_display),
                ("Monitor Baud Rate", format_current_value(current_monitor_baud)),
                ("Version String", format_current_value(current_version, 20)),
                ("Device Code Rule", format_current_value(current_rule, 20))
            ]
            print_config_table(preview_items, 80)
            print()
            
            # Settings menu options
            print_centered("Please select item to configure", 80)
            print()
            
            settings_choices = [
                ('  📡  Serial Port', 'ports'),
                ('  ⚡  Flash Baud Rate', 'flash_baud'),
                ('  📦  Firmware Selection', 'firmware'),
                ('  📊  Monitor Baud Rate', 'monitor_baud'),
                ('  🏷️  Version String', 'version_string'),
                ('  🔢  Device Code Rule', 'device_code_rule'),
                ('  🔄  Reload Default Configuration', 'reload_defaults'),
                ('  ←  Back', 'back')
            ]
            
            # Find the value of last selected item
            default_value = None
            if last_selected:
                # Check if last_selected is in choices
                for _, val in settings_choices:
                    if val == last_selected:
                        default_value = last_selected
                        break
            
            settings_menu = [
                inquirer.List('setting',
                             message="",
                             choices=settings_choices,
                             default=default_value)
            ]
            
            answer = inquirer.prompt(settings_menu)
            if not answer or answer['setting'] == 'back':
                return config_state
            
            setting = answer['setting']
            
            # If separator is selected, redisplay menu
            if setting == 'separator':
                continue
            
            last_selected = setting  # Remember current selection
            
            if setting == 'reload_defaults':
                config_state = reload_default_config(config_state)
                # Save reloaded configuration
                save_config_to_file(config_state)
            elif setting == 'ports':
                config_state = menu_set_ports(config_state)
                save_config_to_file(config_state)
            elif setting == 'flash_baud':
                config_state = menu_set_flash_baud(config_state)
                save_config_to_file(config_state)
            elif setting == 'firmware':
                config_state = menu_set_firmware(config_state)
                save_config_to_file(config_state)
            elif setting == 'monitor_baud':
                config_state = menu_set_monitor_baud(config_state)
                save_config_to_file(config_state)
            elif setting == 'version_string':
                config_state = menu_set_version_string(config_state)
                save_config_to_file(config_state)
            elif setting == 'device_code_rule':
                config_state = menu_set_device_code_rule(config_state)
                save_config_to_file(config_state)
                
        except KeyboardInterrupt:
            return config_state
        except Exception as e:
            print(f"\nError occurred: {e}")


def menu_set_ports(config_state):
    """Set serial port"""
    clear_screen()
    print_header("Set Serial Port", 80)
    
    # Load default configuration (from current mode config)
    default_config = load_default_config(config_state.get('config_path', ''))
    current_port = config_state.get('port', default_config.get('serial_port'))
    
    # Read default serial port from config.json (only for displaying "Use default serial port" option)
    base_config_path = 'config.json'
    default_port = None
    if os.path.exists(base_config_path):
        try:
            with open(base_config_path, 'r', encoding='utf-8') as f:
                base_config = json.load(f)
                default_port = base_config.get('serial_port')
        except:
            pass
    
    # Display current configuration
    print_section_header("Current Configuration", 80)
    print()
    config_items = [("Current Serial Port", current_port if current_port else 'Not set')]
    if default_port:
        config_items.append(("Default Serial Port (config.json)", default_port))
    print_config_table(config_items, 80)
    print()
    
    # List available serial ports (filtered according to config)
    all_ports = serial.tools.list_ports.comports()
    # Load config to get filter rules
    filter_config = load_default_config(config_state.get('config_path', ''))
    ports = filter_serial_ports(all_ports, filter_config)
    port_choices = []
    
    if ports:
        port_choices = [(f"{port.device} - {port.description}", port.device) for port in ports]
    
    # Only show "Use default serial port" option if serial_port exists in config.json
    if default_port:
        port_choices.append(('Use default serial port (config.json)', default_port))
    port_choices.append(('Back', 'back'))
    
    port_question = [
        inquirer.List('port',
                     message="Please select serial port device",
                     choices=port_choices,
                     default=current_port if current_port in [p[1] for p in port_choices] else None)
    ]
    
    answer = inquirer.prompt(port_question)
    if not answer or answer['port'] == 'back':
        return config_state
    
    config_state['port'] = answer['port']
    print(f"\n✓ Serial port selected: {config_state['port']}")
    
    return config_state


def menu_set_flash_baud(config_state):
    """Set flash baud rate"""
    clear_screen()
    print_header("Set Flash Baud Rate", 80)
    
    # Load default configuration
    default_config = load_default_config(config_state.get('config_path', ''))
    default_baud = default_config.get('baud_rate', 921600)
    current_baud = config_state.get('baud_rate', default_baud)
    
    # Display current and default values
    print_section_header("Current Configuration", 80)
    print()
    print_config_table([
        ("Current Baud Rate", str(current_baud)),
        ("Default Baud Rate", str(default_baud))
    ], 80)
    print()
    
    baud_choices = [
        ('115200', 115200),
        ('230400', 230400),
        ('460800', 460800),
        ('921600', 921600),
        
        ('Back', 'back')
    ]
    
    # Find index of current baud rate in list
    default_idx = None
    for idx, (_, val) in enumerate(baud_choices):
        if val == current_baud:
            default_idx = idx
            break
    
    baud_question = [
        inquirer.List('baud',
                     message="Please select flash baud rate",
                     choices=baud_choices,
                     default=default_idx if default_idx is not None else None)
    ]
    
    answer = inquirer.prompt(baud_question)
    if not answer or answer['baud'] == 'back':
        return config_state
    
    config_state['baud_rate'] = answer['baud']
    print(f"\n✓ Flash baud rate set: {config_state['baud_rate']}")
    
    return config_state


def menu_set_firmware(config_state):
    """Set firmware"""
    clear_screen()
    print_header("Set Firmware", 80)
    
    # Load default configuration
    default_config = load_default_config(config_state.get('config_path', ''))
    default_firmware = default_config.get('firmware_path', '')
    current_firmware = config_state.get('firmware', default_firmware)
    
    # Display current and default values
    print_section_header("Current Configuration", 80)
    print()
    print_config_table([
        ("Current Firmware", os.path.basename(current_firmware) if current_firmware else 'Not set'),
        ("Default Firmware", os.path.basename(default_firmware) if default_firmware else 'Not set')
    ], 80)
    print()
    
    # Scan firmware files
    firmware_dir = 'firmware'
    firmware_files = []
    if os.path.exists(firmware_dir):
        # Get all .bin files and sort by modification time (newest first)
        all_files = os.listdir(firmware_dir)
        bin_files_with_time = []
        for f in all_files:
            if f.endswith('.bin'):
                file_path = os.path.join(firmware_dir, f)
                mtime = os.path.getmtime(file_path)
                bin_files_with_time.append((mtime, f))
        
        # Sort by modification time descending (newest first)
        bin_files_with_time.sort(reverse=True)
        firmware_files = [f for _, f in bin_files_with_time]
    
    firmware_choices = []
    
    if firmware_files:
        firmware_choices = [(f, os.path.join(firmware_dir, f)) for f in firmware_files]
    
    if default_firmware and os.path.exists(default_firmware):
        firmware_choices.append(('Use default firmware', default_firmware))
    
    firmware_choices.append(('Back', 'back'))
    
    if not firmware_choices or firmware_choices == [('Back', 'back')]:
        print("Warning: No .bin files found in firmware folder")
        return config_state
    
    # Find index of current firmware in list
    default_idx = None
    for idx, (_, val) in enumerate(firmware_choices):
        if val == current_firmware:
            default_idx = idx
            break
    
    firmware_question = [
        inquirer.List('firmware',
                     message="Please select firmware file",
                     choices=firmware_choices,
                     default=default_idx if default_idx is not None else None)
    ]
    
    answer = inquirer.prompt(firmware_question)
    if not answer or answer['firmware'] == 'back':
        return config_state
    
    config_state['firmware'] = answer['firmware']
    print(f"\n✓ Firmware selected: {os.path.basename(config_state['firmware'])}")
    
    return config_state


def menu_set_monitor_baud(config_state):
    """Set Monitor baud rate"""
    clear_screen()
    print_header("Set Monitor Baud Rate", 80)
    
    # Load default configuration
    default_config = load_default_config(config_state.get('config_path', ''))
    default_baud = default_config.get('monitor_baud', 115200)
    current_baud = config_state.get('monitor_baud', default_baud)
    
    # Display current and default values
    print_section_header("Current Configuration", 80)
    print()
    print_config_table([
        ("Current Monitor Baud Rate", str(current_baud)),
        ("Default Monitor Baud Rate", str(default_baud))
    ], 80)
    print()
    
    baud_choices = [
        ('9600', 9600),
        ('19200', 19200),
        ('38400', 38400),
        ('57600', 57600),
        ('115200', 115200),
        ('230400', 230400),
        ('460800', 460800),
        ('921600', 921600),
        ('1000000', 1000000),
        ('2000000', 2000000),
        ('78400', 78400),
        ('Back', 'back')
    ]
    
    # Find index of current baud rate in list
    default_idx = None
    for idx, (_, val) in enumerate(baud_choices):
        if val == current_baud:
            default_idx = idx
            break
    
    baud_question = [
        inquirer.List('baud',
                     message="Please select Monitor baud rate",
                     choices=baud_choices,
                     default=default_idx if default_idx is not None else None)
    ]
    
    answer = inquirer.prompt(baud_question)
    if not answer or answer['baud'] == 'back':
        return config_state
    
    config_state['monitor_baud'] = answer['baud']
    print(f"\n✓ Monitor baud rate set: {config_state['monitor_baud']}")
    
    return config_state


def menu_set_version_string(config_state):
    """Set version string"""
    clear_screen()
    print_header("Set Version String", 80)
    
    # Load default configuration
    default_config = load_default_config(config_state.get('config_path', ''))
    default_version = default_config.get('version_string', '')
    current_version = config_state.get('version_string', default_version)
    
    # Display current and default values
    print_section_header("Current Configuration", 80)
    print()
    print_config_table([
        ("Current Version String", current_version if current_version else 'Not set'),
        ("Default Version String", default_version if default_version else 'Not set')
    ], 80)
    print()
    
    version_question = [
        inquirer.Text('version',
                     message="Please enter version string",
                     default=current_version)
    ]
    
    answer = inquirer.prompt(version_question)
    if not answer:
        return config_state
    
    config_state['version_string'] = answer['version']
    print(f"\n✓ Version string set: {config_state['version_string']}")
    
    return config_state


def menu_set_device_code_rule(config_state):
    """Set device code rule"""
    clear_screen()
    print_header("Set Device Code Rule", 80)
    
    # Load default configuration
    default_config = load_default_config(config_state.get('config_path', ''))
    default_rule = default_config.get('device_code_rule', '')
    current_rule = config_state.get('device_code_rule', default_rule)
    
    # Display current and default values
    print_section_header("Current Configuration", 80)
    print()
    print_config_table([
        ("Current Encoding Rule", current_rule if current_rule else 'Not set'),
        ("Default Encoding Rule", default_rule if default_rule else 'Not set')
    ], 80)
    print()
    
    rule_choices = [
        ('SN: YYMMDD+Sequence (e.g., SN240101001)', 'SN: YYMMDD+序号'),
        ('Last 6 digits of MAC address', 'MAC后6位'),
        ('Custom rule', 'custom'),
        ('Back', 'back')
    ]
    
    # Find index of current rule in list
    default_idx = None
    for idx, (_, val) in enumerate(rule_choices):
        if val == current_rule:
            default_idx = idx
            break
    
    rule_question = [
        inquirer.List('rule',
                     message="Please select encoding rule",
                     choices=rule_choices,
                     default=default_idx if default_idx is not None else None)
    ]
    
    answer = inquirer.prompt(rule_question)
    if not answer or answer['rule'] == 'back':
        return config_state
    
    if answer['rule'] == 'custom':
        custom_question = [
            inquirer.Text('custom_rule',
                         message="Please enter custom encoding rule",
                         default=current_rule)
        ]
        custom_answer = inquirer.prompt(custom_question)
        if custom_answer:
            config_state['device_code_rule'] = custom_answer.get('custom_rule', '')
    else:
        config_state['device_code_rule'] = answer['rule']
    
    print(f"\n✓ Device code rule set: {config_state['device_code_rule']}")
    
    return config_state


def menu_config_mode(config_state):
    """Configure mode menu"""
    print("\n" + "-"*60)
    print("  Configure Flash Mode")
    print("-"*60)
    
    mode_question = [
        inquirer.List('mode',
                     message="Please select flash mode",
                     choices=[
                         ('Develop Mode (no encryption)', 'develop'),
                         ('Factory Mode (encrypted)', 'factory'),
                         ('← Back to Main Menu', 'back')
                     ])
    ]
    
    answer = inquirer.prompt(mode_question)
    if not answer or answer['mode'] == 'back':
        return config_state
    
    selected_mode = answer['mode']
    
    # Select config file based on mode
    if selected_mode == 'develop':
        config_path = 'config_develop.json'
        mode_name = 'Develop Mode'
    else:
        config_path = 'config_factory.json'
        mode_name = 'Factory Mode'
    
    # Check if config file exists
    if not os.path.exists(config_path):
        print(f"Error: Config file {config_path} does not exist")
        return config_state
    
    # Update configuration state
    config_state['mode'] = selected_mode
    config_state['config_path'] = config_path
    config_state['mode_name'] = mode_name
    
    print(f"\n✓ Selected: {mode_name}")
    
    return config_state


def menu_config_port(config_state):
    """Configure serial port menu"""
    print("\n" + "-"*60)
    print("  Configure Serial Port Device")
    print("-"*60)
    
    # Read default serial port from config.json (only for displaying "Use default serial port" option)
    base_config_path = 'config.json'
    default_port = None
    if os.path.exists(base_config_path):
        try:
            with open(base_config_path, 'r', encoding='utf-8') as f:
                base_config = json.load(f)
                default_port = base_config.get('serial_port')
        except:
            pass
    
    # List available serial ports (filtered according to config)
    all_ports = serial.tools.list_ports.comports()
    # Load config to get filter rules
    if config_state.get('config_path'):
        filter_config = load_default_config(config_state['config_path'])
    else:
        filter_config = load_default_config('config.json')
    ports = filter_serial_ports(all_ports, filter_config)
    port_choices = []
    
    if ports:
        port_choices = [(f"{port.device} - {port.description}", port.device) for port in ports]
    
    # Only show "Use default serial port" option if serial_port exists in config.json
    if default_port:
        port_choices.append(('Use default serial port (config.json)', default_port))
    port_choices.append(('← Back to Main Menu', 'back'))
    
    port_question = [
        inquirer.List('port',
                     message="Please select serial port device",
                     choices=port_choices)
    ]
    
    answer = inquirer.prompt(port_question)
    if not answer or answer['port'] == 'back':
        return config_state
    
    config_state['port'] = answer['port']
    print(f"\n✓ Serial port selected: {config_state['port']}")
    
    return config_state


def menu_config_firmware(config_state):
    """Configure firmware menu"""
    print("\n" + "-"*60)
    print("  Configure Firmware File")
    print("-"*60)
    
    # Load default configuration (if mode is already selected)
    default_firmware = None
    if config_state.get('config_path'):
        try:
            with open(config_state['config_path'], 'r', encoding='utf-8') as f:
                default_config = json.load(f)
                default_firmware = default_config.get('firmware_path', '')
        except:
            pass
    
    # Scan firmware files
    firmware_dir = 'firmware'
    firmware_files = []
    if os.path.exists(firmware_dir):
        # Get all .bin files and sort by modification time (newest first)
        all_files = os.listdir(firmware_dir)
        bin_files_with_time = []
        for f in all_files:
            if f.endswith('.bin'):
                file_path = os.path.join(firmware_dir, f)
                mtime = os.path.getmtime(file_path)
                bin_files_with_time.append((mtime, f))
        
        # Sort by modification time descending (newest first)
        bin_files_with_time.sort(reverse=True)
        firmware_files = [f for _, f in bin_files_with_time]
    
    firmware_choices = []
    
    if firmware_files:
        firmware_choices = [(f, os.path.join(firmware_dir, f)) for f in firmware_files]
    
    if default_firmware and os.path.exists(default_firmware):
        firmware_choices.append(('Use firmware from config file', default_firmware))
    
    firmware_choices.append(('← Back to Main Menu', 'back'))
    
    if not firmware_choices or firmware_choices == [('← Back to Main Menu', 'back')]:
        print("Warning: No .bin files found in firmware folder")
        return config_state
    
    firmware_question = [
        inquirer.List('firmware',
                     message="Please select firmware file",
                     choices=firmware_choices)
    ]
    
    answer = inquirer.prompt(firmware_question)
    if not answer or answer['firmware'] == 'back':
        return config_state
    
    config_state['firmware'] = answer['firmware']
    print(f"\n✓ Firmware selected: {os.path.basename(config_state['firmware'])}")
    
    return config_state


def menu_config_options(config_state):
    """Configure other options menu"""
    print("\n" + "-"*60)
    print("  Configure Other Options")
    print("-"*60)
    
    # Get currently selected options
    current_options = config_state.get('options', [])
    
    options_question = [
        inquirer.Checkbox('options',
                         message="Please select other options (space to select, Enter to confirm)",
                         choices=[
                             ('Skip verification', 'no_verify'),
                             ('Do not reset after flashing', 'no_reset'),
                             ('Erase Flash', 'erase_flash')
                         ],
                         default=current_options)
    ]
    
    answer = inquirer.prompt(options_question)
    if not answer:
        return config_state
    
    config_state['options'] = answer.get('options', [])
    
    if config_state['options']:
        print(f"\n✓ Options selected: {', '.join(config_state['options'])}")
    else:
        print("\n✓ All options cleared")
    
    
    return config_state


def menu_view_config(config_state):
    """View complete configuration"""
    print("\n" + "="*60)
    print("  Complete Configuration Summary")
    print("="*60)
    
    if not config_state.get('mode'):
        print("\n⚠️  Configuration incomplete, please complete the following configuration first:")
        if not config_state.get('mode'):
            print("  - Flash mode")
        if not config_state.get('port'):
            print("  - Serial port device")
        if not config_state.get('firmware'):
            print("  - Firmware file")
    else:
        print(f"\nMode: {config_state.get('mode_name', 'Not set')}")
        print(f"Config file: {config_state.get('config_path', 'Not set')}")
        print(f"Serial port: {config_state.get('port', 'Not set')}")
        print(f"Firmware: {config_state.get('firmware', 'Not set')}")
        if config_state.get('options'):
            print(f"Options: {', '.join(config_state['options'])}")
        else:
            print("Options: None")
    
    print("="*60)


def menu_start_flash(config_state):
    """Start flashing menu - complete automated process"""
    clear_screen()
    print_header("Start Flashing", 80)
    
    # Check if configuration is complete
    if not config_state.get('mode') or not config_state.get('port') or not config_state.get('firmware'):
        print_centered("⚠️  Configuration incomplete, cannot start flashing!", 80)
        print("\nPlease complete the following configuration first:")
        if not config_state.get('mode'):
            print("  - Flash mode")
        if not config_state.get('port'):
            print("  - Serial port device")
        if not config_state.get('firmware'):
            print("  - Firmware file")
        print("\n" + "=" * 80)
        print("Press Enter to return to menu...")
        print("=" * 80)
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            pass
        return False
    
    # Display configuration summary (formatted table)
    print_centered("Configuration Summary", 80)
    print()
    
    config_items = [
        ("Mode", config_state['mode_name']),
        ("Serial Port", config_state['port']),
        ("Flash Baud Rate", config_state.get('baud_rate', 'Not set')),
        ("Firmware", os.path.basename(config_state['firmware']))
    ]
    
    if config_state.get('monitor_baud'):
        config_items.append(("Monitor Baud Rate", config_state['monitor_baud']))
    if config_state.get('version_string'):
        config_items.append(("Version String", config_state['version_string']))
    if config_state.get('device_code_rule'):
        config_items.append(("Device Code Rule", config_state['device_code_rule']))
    
    print_config_table(config_items, 80)
    print()
    
    # Confirm
    confirm_question = [
        inquirer.Confirm('confirm',
                        message="Confirm to start flashing?",
                        default=True)
    ]
    
    confirm_answer = inquirer.prompt(confirm_question)
    if not confirm_answer or not confirm_answer.get('confirm', False):
        print("\nFlashing cancelled")
        return False
    
    # ========== Step 1: Confirm environment (serial port present) ==========
    clear_screen()
    print_header("Step 1/4: Confirm Environment", 80)
    print(f"Checking serial port: {config_state['port']}")
    
    if not check_port_exists(config_state['port']):
        print(f"\n✗ Error: Serial port {config_state['port']} does not exist")
        
        # List available serial ports for user reference
        print("\nAvailable serial port devices:")
        try:
            all_ports = serial.tools.list_ports.comports()
            filter_config = load_default_config(config_state.get('config_path', ''))
            ports = filter_serial_ports(all_ports, filter_config)
            if ports:
                for port in ports:
                    print(f"  - {port.device} - {port.description}")
            else:
                print("  (No available serial ports found)")
        except:
            pass
        
        print("\n" + "=" * 80)
        print("Please check serial port connection, or return to settings menu to modify serial port configuration")
        print("Press Enter to return to menu...")
        print("=" * 80)
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            pass
        return False
    
    print("✓ Serial port exists")
    time.sleep(0.5)
    
    # ========== Step 2: Start flashing ==========
    # Note: Do not detect device here to avoid occupying serial port
    # esptool will automatically detect device when connecting
    clear_screen()
    print_header("Step 2/4: Start Flashing", 80)
    
    # Create flasher instance
    flasher = ESPFlasher(config_state['config_path'])
    flasher.config['serial_port'] = config_state['port']
    flasher.config['firmware_path'] = config_state['firmware']
    
    # If baud rate is set, use the set baud rate
    if config_state.get('baud_rate'):
        flasher.config['baud_rate'] = config_state['baud_rate']
    
    # Automatically adjust Flash parameters based on chip type (before building command)
    flasher.adjust_flash_params()
    
    # Build and display command to be executed
    esptool_path = flasher.check_esptool()
    port = config_state['port']
    firmware_path = config_state['firmware']
    
    # Detect if it's a combined firmware
    is_combined = flasher.is_combined_firmware(firmware_path)
    
    # Build flash command
    cmd_args = [
        esptool_path,
        '--port', port,
        '--baud', str(flasher.config['baud_rate']),
        '--chip', flasher.config['chip_type'],
    ]
    
    # If config requires no reset, add --after no-reset parameter (esptool v5.x uses --after option)
    # --after is a global option, must be placed before write-flash subcommand
    if not flasher.config.get('reset_after_flash', True):
        cmd_args.append('--after')
        cmd_args.append('no-reset')
    
    # Add write-flash subcommand and its options
    cmd_args.extend([
        'write-flash',
        '--flash-mode', flasher.config.get('flash_mode', 'dio'),
        '--flash-freq', flasher.config.get('flash_freq', '40m'),
        '--flash-size', flasher.config.get('flash_size', '4MB'),
    ])
    
    if not flasher.config.get('verify', True):
        cmd_args.append('--no-verify')
    
    # Add firmware address and path
    if is_combined:
        app_offset = '0x0'
    else:
        app_offset = flasher.config.get('app_offset', '0x10000')
    
    cmd_args.extend([app_offset, firmware_path])
    
    # Display command to be executed
    print("\n" + "=" * 80)
    print("Flash command to be executed:")
    print("=" * 80)
    print(f"\nCommand: {' '.join(cmd_args)}")
    print(f"\nDetailed parameters:")
    print(f"  esptool path: {esptool_path}")
    print(f"  Serial port: {port}")
    print(f"  Baud rate: {flasher.config['baud_rate']}")
    print(f"  Chip type: {flasher.config['chip_type']}")
    print(f"  Firmware file: {firmware_path}")
    print(f"  Firmware type: {'Combined (starting from 0x0)' if is_combined else f'App (starting from {app_offset})'}")
    print(f"  Flash mode: {flasher.config.get('flash_mode', 'dio')}")
    print(f"  Flash frequency: {flasher.config.get('flash_freq', '40m')}")
    print(f"  Flash size: {flasher.config.get('flash_size', '4MB')}")
    print(f"  Verify: {'Yes' if flasher.config.get('verify', True) else 'No'}")
    print("=" * 80)
    
    # Confirm whether to continue
    try:
        confirm_choice = [
            inquirer.Confirm('proceed',
                           message="\nPlease check if the above command is correct, confirm to start flashing?",
                           default=True)
        ]
        answer = inquirer.prompt(confirm_choice)
        if not answer or not answer.get('proceed', False):
            print("\nFlashing cancelled")
            return False
    except KeyboardInterrupt:
        print("\n\nUser interrupted operation")
        return False
    
    # Execute flashing or procedures
    try:
        # If it's develop mode and has procedures defined, execute procedures
        mode = config_state.get('mode', '')
        if mode == 'develop' and 'procedures' in flasher.config and flasher.config['procedures']:
            success = flasher.execute_procedures()
        else:
            success = flasher.flash_firmware()
        if not success:
            print("\n" + "=" * 80)
            print("✗ Flashing failed!")
            print("=" * 80)
            print("\nPlease check the above error messages.")
            print("\nReturning to menu in 5 seconds...")
            for i in range(5, 0, -1):
                print(f"\r  Returning in {i} seconds...", end='', flush=True)
                time.sleep(1)
            print("\r" + " " * 50 + "\r", end='')
            return False
    except KeyboardInterrupt:
        print("\n\nUser interrupted operation")
        return False
    except Exception as e:
        print("\n" + "=" * 80)
        print(f"✗ Unexpected error occurred: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        print("\nReturning to menu in 5 seconds...")
        for i in range(5, 0, -1):
            print(f"\r  Returning in {i} seconds...", end='', flush=True)
            time.sleep(1)
        print("\r" + " " * 50 + "\r", end='')
        return False
    
    print("\n✓ Firmware flashing completed")
    
    # Wait for user to press Enter before continuing
    print("\n" + "=" * 80)
    print("Flash log display completed, press Enter to continue to next step...")
    print("=" * 80)
    try:
        input()  # Wait for user to press Enter
    except (KeyboardInterrupt, EOFError):
        print("\nUser interrupted operation")
        return False
    
    # ========== Step 3: Monitor logs and auto input ==========
    clear_screen()
    print_header("Step 3/4: Monitor Device Logs", 80)
    print("Starting serial port monitoring...")
    print("Waiting for device to start and automatically input version and device code...\n")
    
    # Create serial port monitor
    monitor = SerialMonitor(config_state['port'], monitor_baud)
    
    if not monitor.open():
        print("✗ Unable to open serial port for monitoring")
        return False
    
    # Start monitoring
    version_string = config_state.get('version_string', '')
    device_code_rule = config_state.get('device_code_rule', '')
    
    monitor.start_monitoring(version_string, device_code_rule)
    
    # Wait for monitoring to complete (max 2 minutes)
    monitor.wait_for_completion(timeout=120)
    
    # Get device information
    device_info = monitor.get_device_info()
    
    # Close monitoring
    monitor.close()
    
    # Display collected information
    print("\n" + "-" * 80)
    print("Collected device information:")
    print(f"  MAC Address: {device_info.get('mac_address', 'Not obtained')}")
    print(f"  HW Version: {device_info.get('hw_rev', 'Not obtained')}")
    print(f"  SN: {device_info.get('sn', 'Not obtained')}")
    print(f"  Version: {device_info.get('version', 'Not obtained')}")
    print(f"  Device Code: {device_info.get('device_code', 'Not obtained')}")
    print("-" * 80)
    
    # ========== Step 4: Save to CSV ==========
    clear_screen()
    print_header("Step 4/4: Save Record", 80)
    
    # Generate CSV filename (including mode)
    mode = config_state.get('mode', 'unknown')
    csv_file = f"device_records_{mode}_{datetime.now().strftime('%Y%m%d')}.csv"
    
    if save_to_csv(device_info, csv_file):
        print(f"✓ Record saved")
    else:
        print("✗ Failed to save record")
    
    # ========== Complete ==========
    clear_screen()
    print_header("Flashing Process Completed!", 80)
    print("\nWaiting for next startup...")
    print("Press any key to return to main menu...")
    
    return True


def run_tui():
    """Run TUI (with restart support)"""
    while True:
        try:
            run_tui_once()
            # If successfully completed, exit loop
            break
        except RestartTUI:
            # Restart
            continue
        except KeyboardInterrupt:
            print("\n\nUser interrupted operation")
            break
        except Exception as e:
            print(f"\nError occurred: {e}")
            import traceback
            traceback.print_exc()
            break


def main():
    """Main function"""
    # Check if --tui parameter exists (handle with priority)
    if '--tui' in sys.argv:
        run_tui()
        return
    
    # If no parameters (only script name), directly start TUI
    # sys.argv[0] is script name, so len(sys.argv) == 1 means no other parameters
    if len(sys.argv) == 1:
        run_tui()
        return
    
    # Create argument parser
    parser = argparse.ArgumentParser(description='ESP Auto Flashing Tool')
    parser.add_argument('-c', '--config', default='config.json',
                       help='Config file path (default: config.json)')
    parser.add_argument('-m', '--mode', choices=['develop', 'factory'],
                       help='Flash mode: develop (develop mode, no encryption) or factory (factory mode, encrypted)')
    parser.add_argument('-p', '--port', help='Serial port device path (overrides config file)')
    parser.add_argument('-f', '--firmware', help='Firmware file path (overrides config file)')
    parser.add_argument('-l', '--list', action='store_true',
                       help='List all available serial port devices')
    parser.add_argument('--no-verify', action='store_true',
                       help='Skip verification step')
    parser.add_argument('--no-reset', action='store_true',
                       help='Do not reset device after flashing')
    parser.add_argument('--tui', action='store_true',
                       help='Start interactive interface')
    
    # 解析参数
    args = parser.parse_args()
    
    # 如果指定了--tui，启动TUI
    if args.tui:
        run_tui()
        return
    
    # 如果没有任何有效参数（只有默认的config），也启动TUI
    # 检查是否有除了默认config之外的其他参数
    has_other_args = any([
        args.mode, args.port, args.firmware, args.list,
        args.no_verify, args.no_reset
    ])
    
    # 如果config不是默认值，也算有参数
    if args.config != 'config.json':
        has_other_args = True
    
    if not has_other_args:
        # 没有其他参数，启动TUI
        run_tui()
        return
    
    # 根据模式选择配置文件
    config_path = args.config
    if args.mode:
        if args.mode == 'develop':
            config_path = 'config_develop.json'
        elif args.mode == 'factory':
            config_path = 'config_factory.json'
        print(f"使用 {args.mode} 模式配置文件: {config_path}")
    
    # 列出串口
    if args.list:
        flasher = ESPFlasher(config_path)
        flasher.list_ports()
        return
    
    # 创建烧录器实例
    flasher = ESPFlasher(config_path)
    
    # 覆盖配置参数
    if args.port:
        flasher.config['serial_port'] = args.port
    if args.firmware:
        flasher.config['firmware_path'] = args.firmware
    if args.no_verify:
        flasher.config['verify'] = False
    if args.no_reset:
        flasher.config['reset_after_flash'] = False
    
    # 执行烧录或procedures
    try:
        # 如果是开发模式且有procedures定义，执行procedures
        if args.mode == 'develop' and 'procedures' in flasher.config and flasher.config['procedures']:
            success = flasher.execute_procedures()
        else:
            success = flasher.flash_firmware()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n用户中断操作")
        sys.exit(130)
    except Exception as e:
        print(f"\n发生未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

