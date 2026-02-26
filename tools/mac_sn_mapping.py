#!/usr/bin/env python3
"""
从 iCloud 的 all_sn_logs_bog_mac.json 只读加载设备 MAC 与 SN 的映射关系。
不修改该文件，仅用于查询。

用法：
  python tools/mac_sn_mapping.py                    # 打印 MAC -> SN 映射
  python tools/mac_sn_mapping.py --path /path/to/x  # 指定 json 路径
  python -c "from tools.mac_sn_mapping import get_mac_to_sn; print(get_mac_to_sn())"
"""

import json
import os
from typing import Any, Dict, Optional

# iCloud 下的 BOG MAC 用 SN 日志（只读，不修改）
_ICLOUD_BASE = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs"
)
ICLOUD_SN_LOG_PATH = os.path.join(_ICLOUD_BASE, "all_sn_logs_bog_mac.json")


def _normalize_mac(mac: Any) -> str:
    if not mac or not isinstance(mac, str):
        return ""
    return mac.replace(":", "").replace("-", "").strip().upper()


def get_mac_to_sn(sn_log_path: Optional[str] = None) -> Dict[str, str]:
    """
    从 all_sn_logs_bog_mac.json（或指定路径）只读加载 MAC -> SN 映射。
    返回 { mac_normalized: sn }，同一 MAC 多条时保留 generated_at 最新的一条。
    不修改文件。
    """
    path = sn_log_path or ICLOUD_SN_LOG_PATH
    out: Dict[str, str] = {}
    if not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return out
    logs = data.get("logs", data) if isinstance(data, dict) else data
    if not isinstance(logs, list):
        return out
    entries = [
        (e.get("mac_address"), e.get("sn"), e.get("generated_at") or "")
        for e in logs
        if isinstance(e, dict) and e.get("sn")
    ]
    entries.sort(key=lambda x: x[2])
    for mac, sn in ((mac, sn) for mac, sn, _ in entries):
        mac_key = _normalize_mac(mac)
        if mac_key:
            out[mac_key] = sn
    return out


def get_sn_to_mac(sn_log_path: Optional[str] = None) -> Dict[str, str]:
    """
    只读加载 SN -> MAC 映射（同一 SN 多条时保留 generated_at 最新的一条）。
    不修改文件。
    """
    mac_to_sn = get_mac_to_sn(sn_log_path)
    return {sn: mac for mac, sn in mac_to_sn.items()}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="从 iCloud all_sn_logs_bog_mac.json 只读打印 MAC↔SN 映射")
    parser.add_argument("--path", type=str, default=None, help="SN 日志路径，默认 iCloud all_sn_logs_bog_mac.json")
    parser.add_argument("--sn2mac", action="store_true", help="打印 SN -> MAC")
    args = parser.parse_args()
    path = args.path or ICLOUD_SN_LOG_PATH
    if not os.path.isfile(path):
        print(f"文件不存在（只读，不创建）: {path}")
        return
    if args.sn2mac:
        m = get_sn_to_mac(sn_log_path=path)
        print(f"SN -> MAC（共 {len(m)} 条）:")
        for sn, mac in sorted(m.items()):
            print(f"  {sn} -> {mac}")
    else:
        m = get_mac_to_sn(sn_log_path=path)
        print(f"MAC -> SN（共 {len(m)} 条）:")
        for mac, sn in sorted(m.items()):
            print(f"  {mac} -> {sn}")


if __name__ == "__main__":
    main()
