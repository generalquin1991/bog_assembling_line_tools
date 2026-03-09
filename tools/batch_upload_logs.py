#!/usr/bin/env python3
"""
批量遍历并上传烧录与 PCBA 测试日志到 BOG 产测服务。

本脚本仅上传：烧录记录（Burn Record）、PCBA 测试记录（PCBA Test Record），
不上传 Production Test（产测结果由产测 App 单独上报）。

烧录与 PCBA 测试按 MAC 地址合并：同一 MAC 只保留一条烧录（取最新）、一条 PCBA 测试（取最新），
再分别上传。

默认日志目录：~/Library/Mobile Documents/com~apple~CloudDocs/local_data_BOG_MAC
支持通过 --dir 指定其他目录。

API：
- 烧录记录：POST /api/burn-record/batch，单次最多 500 条
- PCBA 测试记录：POST /api/pcba-test-record/batch，单次最多 500 条（macAddress 必填）
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# 默认批量上传的日志根目录（iCloud 下的 local_data_BOG_MAC）
_DEFAULT_LOGS_BASE = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs"
)
DEFAULT_LOG_DIR = os.path.join(_DEFAULT_LOGS_BASE, "local_data_BOG_MAC")

# 批量单次上限
BATCH_SIZE = 500

# 默认 Base URL（测试环境）
DEFAULT_BASE_URL = "http://8.129.99.18:8001"

# 项目根目录（脚本在 tools/ 下）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
# 默认从 iCloud 的 all_sn_logs_bog_mac.json 只读查询 MAC↔SN（不修改该文件）
ICLOUD_SN_LOG_PATH = os.path.join(_DEFAULT_LOGS_BASE, "all_sn_logs_bog_mac.json")
DEFAULT_SN_LOG_PATH = ICLOUD_SN_LOG_PATH

# 与 flash_esp.py 一致：FLASH / TEST 记录中 timestamp 均为 "YYYY-MM-DD HH:MM:SS"
LOCAL_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _ensure_requests():
    try:
        import requests
        return requests
    except ImportError:
        print("请安装 requests: pip install requests", file=sys.stderr)
        sys.exit(1)


def _progress_line(msg: str, finish: bool = False) -> None:
    """单行进度（覆盖刷新），finish 时换行。"""
    pad = 80
    print(f"\r  {msg}", end="")
    if len(msg) < pad:
        print(" " * (pad - len(msg)), end="")
    if finish:
        print()
    sys.stdout.flush()


def _parse_json_blocks(content: str) -> List[dict]:
    """解析文件中多个 JSON 对象（以空行/\\n\\n 分隔）。"""
    blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
    out = []
    for b in blocks:
        try:
            out.append(json.loads(b))
        except json.JSONDecodeError:
            continue
    return out


def _normalize_mac(mac: Any) -> str:
    """统一 MAC 格式：大写、去掉冒号/横线，便于按 MAC 合并。"""
    if not mac or not isinstance(mac, str):
        return "UNKNOWN"
    return mac.replace(":", "").replace("-", "").strip().upper() or "UNKNOWN"


def load_mac_to_sn(sn_log_path: Optional[str] = None) -> Dict[str, str]:
    """
    从 all_sn_logs_bog_mac.json（默认 iCloud）或指定路径只读加载 MAC → SN 映射。
    返回 { mac_normalized: sn }，同一 MAC 多条时保留 generated_at 最新的一条。不修改文件。
    """
    path = sn_log_path or DEFAULT_SN_LOG_PATH
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
    # 按 generated_at 排序，后出现的覆盖先出现的（同 MAC 留最新）
    entries = [
        (e.get("mac_address"), e.get("sn"), e.get("generated_at") or "")
        for e in logs
        if isinstance(e, dict) and e.get("sn")
    ]
    entries.sort(key=lambda x: x[2])
    for mac, sn in ((mac, sn) for mac, sn, _ in entries):
        mac_key = _normalize_mac(mac)
        if mac_key and mac_key != "UNKNOWN":
            out[mac_key] = sn
    return out


def _mac_from_flash(rec: dict) -> str:
    return _normalize_mac(rec.get("mac"))


def _mac_from_test(rec: dict) -> str:
    return _normalize_mac(rec.get("mac") or rec.get("mac_address"))


def _record_timestamp(rec: dict) -> str:
    """用于按时间取最新：返回可排序的时间串，缺省为空。"""
    ts = rec.get("timestamp")
    if not ts or not isinstance(ts, str):
        return ""
    return ts.strip()


def merge_by_mac(
    flash_records: List[dict],
    test_records: List[dict],
) -> List[Tuple[str, Optional[dict], Optional[dict]]]:
    """
    按 MAC 合并烧录与 PCBA 测试记录。同一 MAC 只保留一条烧录（取最新）、一条 PCBA 测试（取最新）。
    返回 [(mac, burn_rec or None, pcba_rec or None), ...]，按 MAC 排序。
    """
    # mac -> (burn_rec, test_rec)，同 MAC 多条时保留 timestamp 最新的一条
    by_mac: Dict[str, Tuple[Optional[dict], Optional[dict]]] = {}
    for rec in flash_records:
        mac = _mac_from_flash(rec)
        if mac not in by_mac:
            by_mac[mac] = (None, None)
        prev = by_mac[mac][0]
        if prev is None or _record_timestamp(rec) > _record_timestamp(prev):
            by_mac[mac] = (rec, by_mac[mac][1])
    for rec in test_records:
        mac = _mac_from_test(rec)
        if mac not in by_mac:
            by_mac[mac] = (None, None)
        prev = by_mac[mac][1]
        if prev is None or _record_timestamp(rec) > _record_timestamp(prev):
            by_mac[mac] = (by_mac[mac][0], rec)
    out: List[Tuple[str, Optional[dict], Optional[dict]]] = [
        (mac, burn, test) for mac, (burn, test) in sorted(by_mac.items())
    ]
    return out


def collect_flash_records(
    log_dir: str,
    verbose: bool = False,
    max_records: Optional[int] = None,
) -> List[dict]:
    """遍历 log_dir 下所有 *_FLASH.json，收集烧录记录。max_records 时达到即停止扫描。"""
    records = []
    if not os.path.isdir(log_dir):
        return records
    names = sorted(n for n in os.listdir(log_dir) if n.endswith("_FLASH.json"))
    total_files = len(names)
    for idx, name in enumerate(names, 1):
        if max_records is not None and len(records) >= max_records:
            break
        path = os.path.join(log_dir, name)
        if not os.path.isfile(path):
            continue
        if verbose:
            _progress_line(f"烧录: 第 {idx}/{total_files} 个文件, 已收集 {len(records)} 条")
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        for rec in _parse_json_blocks(content):
            if isinstance(rec, dict):
                records.append(rec)
                if max_records is not None and len(records) >= max_records:
                    records = records[:max_records]
                    if verbose:
                        _progress_line(f"烧录: 第 {idx}/{total_files} 个文件, 已收集 {len(records)} 条 (已达上限 {max_records}，停止)", finish=True)
                    return records
    if verbose and total_files:
        _progress_line(f"烧录: 共 {total_files} 个文件, {len(records)} 条记录", finish=True)
    return records


def collect_test_records(
    log_dir: str,
    verbose: bool = False,
    max_records: Optional[int] = None,
) -> List[dict]:
    """遍历 log_dir 下所有 *_TEST.json，收集 PCBA 测试记录。max_records 时达到即停止扫描。"""
    records = []
    if not os.path.isdir(log_dir):
        return records
    names = sorted(n for n in os.listdir(log_dir) if n.endswith("_TEST.json"))
    total_files = len(names)
    for idx, name in enumerate(names, 1):
        if max_records is not None and len(records) >= max_records:
            break
        path = os.path.join(log_dir, name)
        if not os.path.isfile(path):
            continue
        if verbose:
            _progress_line(f"PCBA: 第 {idx}/{total_files} 个文件, 已收集 {len(records)} 条")
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        for rec in _parse_json_blocks(content):
            if isinstance(rec, dict):
                records.append(rec)
                if max_records is not None and len(records) >= max_records:
                    records = records[:max_records]
                    if verbose:
                        _progress_line(f"PCBA: 第 {idx}/{total_files} 个文件, 已收集 {len(records)} 条 (已达上限 {max_records}，停止)", finish=True)
                    return records
    if verbose and total_files:
        _progress_line(f"PCBA: 共 {total_files} 个文件, {len(records)} 条记录", finish=True)
    return records


def flash_record_to_burn_payload(
    rec: dict,
    mac_to_sn: Optional[Dict[str, str]] = None,
) -> dict:
    """将本地 FLASH 记录转为 /api/burn-record 单条请求体。"""
    mac = rec.get("mac") or "UNKNOWN"
    mac_key = _normalize_mac(mac)
    # deviceSerialNumber 必填：优先从 all_sn_logs 按 MAC 解析，再记录内 SN，否则 MAC 占位
    sn = None
    if mac_to_sn and mac_key and mac_key != "UNKNOWN":
        sn = mac_to_sn.get(mac_key)
    sn = (
        sn
        or rec.get("device_serial_number")
        or rec.get("sn")
        or (f"MAC-{mac}" if mac != "UNKNOWN" else "UNKNOWN")
    )
    # 设备被写入的 RTC 时间戳（若本地日志有则上传，格式与 FLASH 一致：YYYY-MM-DD HH:MM:SS）
    device_written_ts = (
        _to_upload_ts(rec.get("device_written_timestamp"))
        or _to_upload_ts(rec.get("device_rtc_time"))
        or _to_upload_ts(rec.get("device_rtc"))
    )
    # 写入设备的 SN：有真实 SN 时填写，否则不送
    device_written_sn = sn if (sn and not str(sn).startswith("MAC-")) else None
    payload = {
        "deviceSerialNumber": sn,
        "macAddress": rec.get("mac_address") or mac,
        "burnStartTime": _to_upload_ts(rec.get("timestamp")),
        "burnDurationSeconds": rec.get("duration_sec"),
        "binFileName": _basename(rec.get("firmware")),
        "deviceWrittenTimestamp": device_written_ts,
        "deviceWrittenSerialNumber": device_written_sn,
        "burnTestResult": "passed" if rec.get("success") else "self_check_failed",
    }
    # 去掉值为 None 的键，避免 API 报错
    return {k: v for k, v in payload.items() if v is not None}


def _format_mac_colon(mac: str) -> str:
    """将 6825DDAB2D04 格式化为 68:25:DD:AB:2D:04，便于 API 展示。"""
    mac = (mac or "").replace(":", "").replace("-", "").upper()
    if len(mac) != 12 or mac == "UNKNOWN":
        return mac
    return ":".join(mac[i : i + 2] for i in range(0, 12, 2))


def test_record_to_pcba_payload(
    rec: dict,
    mac_to_sn: Optional[Dict[str, str]] = None,
) -> dict:
    """将本地 *_TEST.json 记录转为 /api/pcba-test-record 单条请求体（MAC 为主标识）。"""
    mac_raw = rec.get("mac") or rec.get("mac_address") or "UNKNOWN"
    mac_address = _format_mac_colon(mac_raw)
    mac_key = _normalize_mac(mac_raw)
    sn = None
    if mac_to_sn and mac_key and mac_key != "UNKNOWN":
        sn = mac_to_sn.get(mac_key)
    sn = (
        sn
        or (rec.get("serial_number") or {}).get("value")
        or rec.get("device_serial_number")
        or rec.get("sn")
        or ""
    )
    # 汇总步骤判定通过与否
    steps = []
    for key, step_id in [
        ("rtc", "rtc"),
        ("pressure_sensor", "pressure_sensor"),
        ("button_test", "button_test"),
        ("factory_config_complete", "factory_config_complete"),
    ]:
        step = rec.get(key)
        if isinstance(step, dict):
            status = step.get("status", "not_detected")
            steps.append({"stepId": step_id, "status": status})
    passed = all(
        s.get("status") == "pass" or s.get("status") == "passed"
        for s in steps
    )
    test_result = "passed" if passed else "failed"
    payload = {
        "macAddress": mac_address,
        "deviceSerialNumber": sn if (sn and sn.strip()) else None,
        "testResult": test_result,
        "testTime": _to_upload_ts(rec.get("timestamp")),
        "durationSeconds": rec.get("duration_sec"),
        "testDetails": {"stepsSummary": steps} if steps else None,
    }
    return {k: v for k, v in payload.items() if v is not None}


def _parse_local_ts(ts: Any) -> Optional[datetime]:
    """解析 FLASH/TEST 本地时间戳，返回 datetime 或 None。支持 YYYY-MM-DD HH:MM:SS 与带 T/Z 的 ISO。"""
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()[:26].replace("Z", "")
    if not s:
        return None
    # 统一成 "YYYY-MM-DD HH:MM:SS" 再解析（与 flash_esp 写入格式一致）
    s_norm = s.replace("T", " ")[:19]
    try:
        return datetime.strptime(s_norm, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _to_upload_ts(ts: Any) -> Optional[str]:
    """按 FLASH/TEST 本地格式上传时间戳：YYYY-MM-DD HH:MM:SS（与 flash_esp 写入格式一致）。"""
    dt = _parse_local_ts(ts)
    return dt.strftime(LOCAL_TS_FMT) if dt else (ts if isinstance(ts, str) and ts.strip() else None)


def _to_iso(ts: Any) -> Optional[str]:
    """将本地时间戳转为 ISO 8601（需 ISO 的接口时用）。"""
    dt = _parse_local_ts(ts)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else (ts if isinstance(ts, str) and ts.strip() else None)


def _basename(path: Any) -> Optional[str]:
    if not path or not isinstance(path, str):
        return None
    return os.path.basename(path)


def upload_batch(
    base_url: str,
    path: str,
    records: List[dict],
    dry_run: bool,
) -> Tuple[int, List[str]]:
    """
    上传一批记录。返回 (成功数, 错误信息列表)。
    """
    if dry_run:
        return len(records), []
    requests = _ensure_requests()
    url = base_url.rstrip("/") + path
    try:
        r = requests.post(url, json={"records": records}, timeout=60)
        r.raise_for_status()
        data = r.json()
        count = data.get("count", len(records))
        return count, []
    except requests.RequestException as e:
        return 0, [str(e)]
    except (ValueError, KeyError) as e:
        return 0, [str(e)]


def run(
    log_dir: str,
    base_url: str,
    dry_run: bool,
    upload_flash: bool,
    upload_test: bool,
    count: Optional[int] = None,
    sn_log_path: Optional[str] = None,
) -> None:
    """扫描目录并批量上传烧录与 PCBA 测试（非 Production Test）。"""
    # 未指定则默认同时上传烧录与 PCBA 测试
    if not upload_flash and not upload_test:
        upload_flash = True
        upload_test = True
    if not os.path.isdir(log_dir):
        print(f"目录不存在: {log_dir}")
        sys.exit(1)

    print(f"日志目录: {log_dir}")
    if count is not None:
        print(f"限定只处理前 {count} 个 MAC (--count {count})\n")
    if dry_run:
        print("(dry-run，仅扫描与转换，不发送请求)\n")
    total_burn_ok = 0
    total_burn_fail = 0
    total_test_ok = 0
    total_test_fail = 0

    # 收集：需要烧录则扫 FLASH，需要 PCBA 测试则扫 TEST；按 MAC 合并时多扫一些以凑够 MAC 数
    max_records = (count * 4) if count is not None else None
    flash_records: List[dict] = []
    test_records: List[dict] = []

    if upload_flash:
        print("扫描烧录日志 (*_FLASH.json)...")
        flash_records = collect_flash_records(
            log_dir, verbose=True, max_records=max_records
        )
        print()
    if upload_test:
        print("扫描 PCBA 测试日志 (*_TEST.json)...")
        test_records = collect_test_records(
            log_dir, verbose=True, max_records=max_records
        )
        print()

    # 按 MAC 合并：同一 MAC 只保留一条烧录（最新）、一条 PCBA 测试（最新）
    merged = merge_by_mac(flash_records, test_records)
    if count is not None:
        merged = merged[:count]
        print(f"按 MAC 合并后取前 {count} 个 MAC: 共 {len(merged)} 个设备\n")
    else:
        print(f"按 MAC 合并: 共 {len(merged)} 个设备 (烧录 {sum(1 for _, b, _ in merged if b)} 条, PCBA 测试 {sum(1 for _, _, t in merged if t)} 条)\n")

    # 从 data/all_sn_logs.json 按 MAC 解析真实 SN（可选）
    sn_log_path = sn_log_path or DEFAULT_SN_LOG_PATH
    mac_to_sn = load_mac_to_sn(sn_log_path=sn_log_path)
    if mac_to_sn:
        print(f"已加载 MAC→SN 映射: {sn_log_path}，共 {len(mac_to_sn)} 条\n")
    burn_payloads = [
        flash_record_to_burn_payload(r, mac_to_sn=mac_to_sn)
        for _, r, _ in merged
        if r is not None
    ]
    pcba_payloads = [
        test_record_to_pcba_payload(r, mac_to_sn=mac_to_sn)
        for _, _, r in merged
        if r is not None
    ]

    if upload_flash and burn_payloads:
        num_batches = (len(burn_payloads) + BATCH_SIZE - 1) // BATCH_SIZE or 1
        for i in range(0, len(burn_payloads), BATCH_SIZE):
            chunk = burn_payloads[i : i + BATCH_SIZE]
            batch_no = i // BATCH_SIZE + 1
            print(f"  [烧录] 第 {batch_no}/{num_batches} 批, 本批 {len(chunk)} 条", end="")
            if dry_run:
                print(" (dry-run 跳过)")
            else:
                print(" ...")
            n, errs = upload_batch(
                base_url, "/api/burn-record/batch", chunk, dry_run
            )
            if errs:
                total_burn_fail += len(chunk)
                for e in errs:
                    print(f"      错误: {e}")
            else:
                total_burn_ok += n
        print(f"烧录记录: 共 {len(burn_payloads)} 条, 成功 {total_burn_ok}, 失败 {total_burn_fail}\n")

    if upload_test and pcba_payloads:
        num_batches = (len(pcba_payloads) + BATCH_SIZE - 1) // BATCH_SIZE or 1
        for i in range(0, len(pcba_payloads), BATCH_SIZE):
            chunk = pcba_payloads[i : i + BATCH_SIZE]
            batch_no = i // BATCH_SIZE + 1
            print(f"  [PCBA 测试] 第 {batch_no}/{num_batches} 批, 本批 {len(chunk)} 条", end="")
            if dry_run:
                print(" (dry-run 跳过)")
            else:
                print(" ...")
            n, errs = upload_batch(
                base_url, "/api/pcba-test-record/batch", chunk, dry_run
            )
            if errs:
                total_test_fail += len(chunk)
                for e in errs:
                    print(f"      错误: {e}")
            else:
                total_test_ok += n
        print(f"PCBA 测试记录: 共 {len(pcba_payloads)} 条, 成功 {total_test_ok}, 失败 {total_test_fail}\n")

    if dry_run:
        print("(dry-run 结束，未实际发送请求)")


def main():
    parser = argparse.ArgumentParser(
        description="批量上传烧录与 PCBA 测试日志到 BOG 产测服务（不上传 Production Test）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
默认日志目录: %s
生产: --base-url http://8.129.99.18:8080
测试: --base-url http://8.129.99.18:8001 (默认)，规范端口 8081 可用
        """ % DEFAULT_LOG_DIR,
    )
    parser.add_argument(
        "--dir",
        default=DEFAULT_LOG_DIR,
        help="批量日志所在目录（默认: %s）" % DEFAULT_LOG_DIR,
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="服务 Base URL（默认测试 8001）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只扫描与转换，不发送请求",
    )
    parser.add_argument(
        "--flash",
        action="store_true",
        help="上传烧录记录（*_FLASH.json）；不指定 --flash/--test 时默认两者都上传",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="上传 PCBA 测试记录（*_TEST.json）；不指定时默认两者都上传",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        metavar="N",
        help="测试时限定只处理前 N 个 MAC（按 MAC 合并后的设备数）",
    )
    parser.add_argument(
        "--sn-log",
        type=str,
        default=None,
        metavar="PATH",
        help="SN 日志路径，用于按 MAC 解析真实 SN（只读）；默认 iCloud all_sn_logs_bog_mac.json",
    )
    args = parser.parse_args()
    if args.count is not None and args.count < 1:
        parser.error("--count 必须为正整数")
    run(
        log_dir=args.dir,
        base_url=args.base_url,
        dry_run=args.dry_run,
        upload_flash=args.flash,
        upload_test=args.test,
        count=args.count,
        sn_log_path=args.sn_log,
    )


if __name__ == "__main__":
    main()
