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
from datetime import datetime
from typing import Optional


class HashVerificationError(Exception):
    """日志文件哈希验证失败异常"""
    pass


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


def load_sn_config(config_path: str = "sn_config.json") -> dict:
    """
    加载序列号配置文件
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        dict: 配置信息，包含 computer_id, current_week, sequence_number, last_generated_at, last_generated_sn, status
    """
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 确保所有必需的字段存在
                config.setdefault('computer_id', 1)
                config.setdefault('current_week', '0000')
                config.setdefault('sequence_number', 0)
                config.setdefault('last_generated_at', None)
                config.setdefault('last_generated_sn', None)
                config.setdefault('status', 'pending')  # pending, occupied, failed
                return config
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: 读取配置文件失败: {e}")
            return {'computer_id': 1, 'current_week': '0000', 'sequence_number': 0, 
                   'last_generated_at': None, 'last_generated_sn': None, 'status': 'pending'}
    else:
        # 如果文件不存在，创建默认配置
        default_config = {
            'computer_id': 1, 
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
    保存序列号配置到文件
    
    Args:
        config: 配置信息
        config_path: 配置文件路径
        
    Returns:
        bool: 是否保存成功
    """
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except IOError as e:
        print(f"错误: 保存配置文件失败: {e}")
        return False


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
    
    Args:
        log_path: 日志文件路径
        verify_hash: 是否验证哈希值（默认True）
        raise_on_error: 验证失败时是否抛出异常（默认True，用于防止重复序列号）
        
    Returns:
        list: 历史日志列表
        
    Raises:
        HashVerificationError: 当哈希验证失败且 raise_on_error=True 时
    """
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
    
    Args:
        logs: 日志列表
        log_path: 日志文件路径
        
    Returns:
        bool: 是否保存成功
    """
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
    
    Args:
        log_path: 日志文件路径
        
    Returns:
        tuple: (是否验证通过, 消息)
    """
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
                log_path: str = "all_sn_logs.json", force: bool = False) -> str:
    """
    生成序列号
    
    格式: 64YYWWXnnnnn
    - 64: 固定前缀
    - YY: 年份后两位
    - WW: ISO周数 (01-53)
    - X: 电脑编号 (1-9)
    - nnnnn: 序列号 (00001-99999)
    
    Args:
        computer_id: 电脑编号，如果为None则从配置文件读取
        config_path: 配置文件路径
        log_path: 日志文件路径
        force: 是否强制继续（即使hash验证失败，不推荐使用）
        
    Returns:
        str: 生成的序列号
        
    Raises:
        ValueError: 如果序列号超过99999或电脑编号无效
        HashVerificationError: 当哈希验证失败且 force=False 时
    """
    # 加载配置
    config = load_sn_config(config_path)
    
    # 获取电脑编号
    if computer_id is None:
        computer_id = config.get('computer_id', 1)
    
    # 验证电脑编号范围 (1-9)
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
    
    # 更新配置
    config['sequence_number'] = sequence_number
    config['computer_id'] = computer_id
    
    # 生成序列号
    sn = f"64{yy}{ww}{computer_id}{sequence_number:05d}"
    
    # 记录生成时间和序列号
    now = datetime.now()
    config['last_generated_at'] = now.isoformat()
    config['last_generated_sn'] = sn
    config['status'] = 'pending'  # 新生成的序列号默认为pending状态
    
    # 保存配置
    if not save_sn_config(config, config_path):
        print("警告: 配置保存失败，但序列号已生成")
    
    # 添加到历史日志（会验证hash，如果失败会抛出异常）
    try:
        add_sn_log(sn, computer_id, current_week, status='pending', log_path=log_path, force=force)
    except HashVerificationError as e:
        # 如果hash验证失败，回滚序列号（不保存配置）
        config['sequence_number'] = stored_sequence
        save_sn_config(config, config_path)
        raise
    
    return sn


def get_current_status(config_path: str = "sn_config.json") -> dict:
    """
    获取当前序列号生成器状态
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        dict: 包含 computer_id, current_week, sequence_number, next_sn 等信息
    """
    config = load_sn_config(config_path)
    yy, ww = get_iso_week()
    current_week = yy + ww
    
    status = {
        'computer_id': config.get('computer_id', 1),
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
    设置电脑编号
    
    Args:
        computer_id: 电脑编号 (1-9)
        config_path: 配置文件路径
        
    Returns:
        bool: 是否设置成功
    """
    if not (1 <= computer_id <= 9):
        print(f"错误: 电脑编号必须在1-9之间，当前值: {computer_id}")
        return False
    
    config = load_sn_config(config_path)
    config['computer_id'] = computer_id
    return save_sn_config(config, config_path)


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
    
    parser = argparse.ArgumentParser(description='序列号生成器 - 格式: 64YYWWXnnnnn')
    parser.add_argument('--generate', '-g', action='store_true', help='生成一个新的序列号')
    parser.add_argument('--status', '-s', action='store_true', help='显示当前状态')
    parser.add_argument('--set-computer-id', type=int, metavar='ID', help='设置电脑编号 (1-9)')
    parser.add_argument('--reset', action='store_true', help='重置当前周的序列号')
    parser.add_argument('--update-status', type=str, metavar='STATUS', help='更新序列号状态 (occupied/failed/pending)')
    parser.add_argument('--sn', type=str, metavar='SN', help='要更新状态的序列号（需配合--update-status使用）')
    parser.add_argument('--mac', type=str, metavar='MAC', help='MAC地址（可选，配合--update-status使用）')
    parser.add_argument('--verify', action='store_true', help='验证日志文件的哈希值')
    parser.add_argument('--force', action='store_true', help='强制继续（即使hash验证失败，不推荐使用）')
    parser.add_argument('--config', type=str, default='sn_config.json', help='配置文件路径 (默认: sn_config.json)')
    parser.add_argument('--log', type=str, default='all_sn_logs.json', help='日志文件路径 (默认: all_sn_logs.json)')
    
    args = parser.parse_args()
    
    # 如果没有指定任何操作，默认生成序列号
    if not any([args.generate, args.status, args.set_computer_id is not None, args.reset, args.update_status, args.verify]):
        args.generate = True
    
    if args.set_computer_id is not None:
        if set_computer_id(args.set_computer_id, args.config):
            print(f"✓ 电脑编号已设置为: {args.set_computer_id}")
        else:
            print("✗ 设置电脑编号失败")
        return
    
    if args.verify:
        is_valid, message = verify_sn_logs(args.log)
        print(message)
        return 0 if is_valid else 1
    
    if args.update_status:
        if not args.sn:
            print("错误: 使用 --update-status 时必须指定 --sn")
            return 1
        valid_statuses = ['pending', 'occupied', 'failed']
        if args.update_status not in valid_statuses:
            print(f"错误: 状态必须是以下之一: {', '.join(valid_statuses)}")
            return 1
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
        status = get_current_status(args.config)
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
        try:
            sn = generate_sn(config_path=args.config, log_path=args.log, force=args.force)
            print(sn)
        except HashVerificationError as e:
            print(str(e))
            return 1
        except ValueError as e:
            print(f"错误: {e}")
            return 1
        except Exception as e:
            print(f"错误: 生成序列号失败: {e}")
            return 1


if __name__ == '__main__':
    exit(main() or 0)

