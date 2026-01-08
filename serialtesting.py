#!/usr/bin/env python3
"""诊断脚本：验证串口数据捕获的完整性和时序"""
import serial
import time
import sys
import threading
from collections import deque
import esptool


PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.wchusbserial110"
BAUD = 78400  # monitor波特率（写死，不要修改）
BOOTLOADER_BAUD = 115200  # bootloader波特率（写死，不要修改）

# 时间设置（用户可自行调整）
WARMUP_LISTEN_TIME = 0.1  # 预热阶段监听时间（秒）
DOWNLOAD_MODE_LISTEN_TIME = 0.5  # download模式监听时间（秒）
RUN_LISTEN_TIME = 1.0  # run后监听时间（秒）
SERIAL_RELEASE_WAIT = 0.2  # 串口释放等待时间（秒）
STOP_LOGGING_WAIT = 0.2  # 停止监听时的等待时间（秒）

print(f"诊断串口: {PORT}")
print(f"波特率: {BAUD}\n")

# 全局变量
ser = None
stop_reading = False
all_data = bytearray()
total_bytes = 0
read_count = 0
lock = threading.Lock()


def open_serial():
    """打开串口用于日志监听。"""
    global ser
    if ser is not None and ser.is_open:
        return
    print(f"打开串口: {PORT} @ {BAUD}")
    ser = serial.Serial(PORT, BAUD, timeout=0.05)


def close_serial():
    """关闭串口。"""
    global ser
    if ser is not None:
        try:
            ser.close()
        except Exception:
            pass
    ser = None


def reader_thread():
    """后台读取串口数据，用于观察 ESP 日志与时序。"""
    global ser, stop_reading, all_data, total_bytes, read_count
    while not stop_reading:
        if ser is None or not ser.is_open:
            time.sleep(0.01)
            continue
        try:
            data = ser.read(1024)
        except Exception as e:
            print(f"[reader] 串口读取异常: {e}")
            time.sleep(0.1)
            continue

        if not data:
            time.sleep(0.005)
            continue

        now = time.time()
        with lock:
            all_data.extend(data)
            total_bytes += len(data)
            read_count += 1

        # 打印为字符串
        try:
            text = data.decode('utf-8', errors='replace')
            print(f"[{now:.6f}] +{len(data):4d} bytes : {text}", end='')
        except Exception:
            # 如果解码失败，回退到十六进制
            hex_str = data.hex(" ")
            print(f"[{now:.6f}] +{len(data):4d} bytes (hex): {hex_str}")


def start_logging():
    """开启串口监听线程。"""
    global stop_reading
    stop_reading = False
    open_serial()
    t = threading.Thread(target=reader_thread, daemon=True)
    t.start()
    return t


def stop_logging():
    """停止串口监听线程并关闭串口。"""
    global stop_reading
    stop_reading = True
    # 给 reader 一点时间退出
    time.sleep(STOP_LOGGING_WAIT)
    close_serial()


def run_esptool(args):
    """
    直接调用 esptool.main()，避免创建子进程。
    esptool.main() 内部会调用 sys.exit()，这里捕获掉。
    """
    print("\n================ esptool 调用 ================")
    print("esptool 参数:", " ".join(args))
    print("=============================================\n")

    old_argv = sys.argv
    sys.argv = ["esptool.py"] + args
    try:
        esptool.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
        if code != 0:
            print(f"esptool 退出码: {code}")
    finally:
        sys.argv = old_argv


def reset_to_download_mode():
    """
    使用 esptool 复位并进入 download 模式。

    说明：
    - esptool 在执行期间会独占串口，因此监听日志的阶段分为：
      1) esptool 调用前后我们单独开启串口监听；
      2) esptool 调用本身内部的 bootloader 交互不再额外截获。
    """
    print("\n====== 步骤 1: 复位并进入 download 模式 ======\n")

    # 先短时间监听当前运行日志，确认串口 OK
    print(f">>> 预热阶段：监听当前 ESP 日志 {WARMUP_LISTEN_TIME} 秒...")
    start_logging()
    time.sleep(WARMUP_LISTEN_TIME)
    stop_logging()

    # 确保串口没有被占用（esptool 需要独占串口）
    stop_logging()
    time.sleep(SERIAL_RELEASE_WAIT)  # 确保串口完全释放
    
    # 调用 esptool，使其通过 DTR/RTS 复位并进入 bootloader
    print(">>> 调用 esptool，使芯片进入 download 模式 (chip_id)...")
    run_esptool(
        [
            "--port",
            PORT,
            "--baud",
            str(BOOTLOADER_BAUD),
            "--before",
            "default-reset",
            "--after",
            "no-reset",
            "read_mac",
        ]
    )

    # esptool 完成后，再次开启监听，观察此时串口是否稳定
    print(f">>> esptool 完成，重新开启监听 {DOWNLOAD_MODE_LISTEN_TIME} 秒（处于 download 模式）...")
    start_logging()
    time.sleep(DOWNLOAD_MODE_LISTEN_TIME)
    stop_logging()
    print(">>> 步骤 1 完成。\n")


def run_user_code_with_log():
    """
    在已经处于 download 模式的前提下：
    1) 使用 esptool 发送 run 命令启动用户程序（会触发 hard reset）；
    2) esptool 完成后立即开启串口监听，捕获用户程序启动日志。
    """
    print("\n====== 步骤 2: run 并监听 ESP 日志 ======\n")

    # 确保串口没有被占用（esptool 需要独占串口）
    print(">>> 确保串口可用，准备调用 esptool...")
    stop_logging()
    time.sleep(SERIAL_RELEASE_WAIT)  # 确保串口完全释放
    
    print(">>> 使用 esptool 发送 run 命令启动用户程序（会触发 hard reset）...")
    run_esptool(
        [
            "--port",
            PORT,
            "--baud",
            str(BOOTLOADER_BAUD),
            # "--before",
            # "no-reset",
            # "--after",
            # "hard-reset",
            "run",
        ]
    )
    start_logging()
    # esptool 完成后，立即开启监听，捕获 hard reset 后的启动日志
    print(f">>> run 完成，立即开启监听 {RUN_LISTEN_TIME} 秒，捕获启动日志...")
    
    time.sleep(RUN_LISTEN_TIME)
    stop_logging()

    print(">>> 步骤 2 完成。\n")


def main():
    print("========== 串口诊断流程开始 ==========")
    print("1) 使用 esptool 复位并进入 download 模式，并在前后监听串口日志")
    print("2) 使用 esptool 执行 run，然后监听 ESP 日志\n")

    # reset_to_download_mode()
    run_user_code_with_log()

    print("========== 串口诊断流程结束 ==========")
    print(f"总共捕获字节数: {total_bytes}")
    print(f"读取次数: {read_count}")


if __name__ == "__main__":
    main()
